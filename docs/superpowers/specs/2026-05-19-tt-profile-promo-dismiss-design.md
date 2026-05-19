# WP #106 — TT profile-tab promo-modal dismiss

**Дата**: 2026-05-19
**WP**: [OpenProject #106](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/106)
**Связанные**: WP #67 Layer 2 (PR #70 SHIPPED 2026-05-18) — тот же паттерн на post-switch site
**Evidence**: `docs/evidence/2026-05-19-tt-fails-triage.md` (worktree `worktree-wt-tt-triage-2026-05-19`)

## 1. Контекст и симптом

В `account_switcher.py::_switch_tiktok` после tap на bottom-nav «Я» работает retap-loop (3 итерации: обычный tap → smart_tap → cold-start force-stop+relaunch). На каждой итерации:

1. `xml_probe = self.p.dump_ui(...)`.
2. `_tt_dismiss_security_prompt(xml_probe)` — закрывает security sheet («Быстрая проверка безопасности»).
3. `_tt_is_own_profile(xml_probe)` — break при успехе.
4. Иначе ветвимся: logged_out → fail, reauth → fail, foreign_profile → bottomsheet recovery, else retap.

После 3 неудач — `_fail(step='tt_2_not_own_profile')`, который мапится в `error_code='tt_profile_tab_broken'`.

За 2026-05-19 — 4 фейла (24% всех TT-фейлов дня после исключения сетевой проблемы). Семидневная динамика 31/7д устойчиво. Из retap-дампов всех 4 кейсов: поверх собственного профиля висит **promo-модалка TikTok**, которая sticky переживает `force-stop`+relaunch:

| вариант | пример | кнопки |
|---|---|---|
| Контакты promo | «Чтобы связаться в TikTok со своими знакомыми, разрешите приложению доступ к контактам в настройках устройства.» | «Открыть настройки» / «Не разрешать» |
| Facebook friends promo | «Разрешить TikTok доступ к списку ваших друзей в Facebook и почтовому адресу?» | «OK» / «Не разрешать» |

Оба диалога имеют `content-desc="Диалог"` (НЕ «Нижняя шторка»), поэтому существующий `_tt_dismiss_security_prompt` (whitelist на `'Быстрая проверка безопасности' + 'Нижняя шторка'`) их не матчит.

Финальный fail-дамп (снят уже после `_fail`) у всех 4 кейсов показывает корректный own-profile → модалка автозакрывается позже, но switcher успевает отказать.

## 2. Цель

Распознавать и закрывать известные promo-модалки внутри retap-loop ДО `_tt_is_own_profile`, по тому же паттерну что WP #67 Layer 2 (PR #70).

**Success criteria**:
- 4 сегодняшних кейса (7827, 7861, 7870, 7884) при re-queue должны пройти switcher.
- Семидневный bleeder `tt_profile_tab_broken` (3-7/день) уйти в околонулевой trend в течение 7д после деплоя.
- 0 регрессий в существующих тестах switcher'а.
- 0 ложных tap'ов «Не разрешать» в неродственных контекстах (защита через title-match).

## 3. Архитектура

Зеркалит WP #67 Layer 2 один-в-один (минимальный отход от проверенного шаблона):

### 3.1. Module-level constant

В `account_switcher.py` рядом с `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (~line 220):

```python
# [WP #106 — 2026-05-19] Whitelist profile-tab promo-modals.
# Evidence: tasks 7827/7861/7884 (contacts promo), 7870 (FB friends promo).
# Match требует BOTH title_substr AND clickable button_text — защита от
# ложного dismiss другого «Не разрешать» в неродственном контексте.
# Расширяется по одной строке при появлении новой evidence.
_TT_PROFILE_PROMO_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # (title_substring, dismiss_button_text)
    ('Чтобы связаться в TikTok', 'Не разрешать'),
    ('Разрешить TikTok доступ к списку ваших друзей', 'Не разрешать'),
)
```

### 3.2. Module-level helper (detect-only)

```python
def _tt_try_dismiss_profile_promo(xml: str) -> Optional[tuple[str, str]]:
    """[WP #106 — 2026-05-19] Detect known dismissible TT profile-tab promo-modal.

    Используется в `AccountSwitcher._switch_tiktok` retap-loop, чтобы
    отличить случай "TT показал promo-модалку поверх профиля" от настоящего
    `not-own-profile` fail'а. Match требует ОБА условия:
      - элемент с `title_substr` в `.label` где-то на экране;
      - clickable элемент с `.label.strip().lower() == button_text.lower()`.

    Title-check защищает от ложного dismiss другого «Не разрешать»/«Don't allow»
    в другом контексте (permission-prompt системы, alert-диалог TT и т.п.).

    Returns: (title_substr, button_text) первой совпавшей записи whitelist;
    None если ни одна не сматчилась.
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)  # уже возвращает [] на parse error / FLAG_SECURE
    if not elements:
        return None
    for title_substr, button_text in _TT_PROFILE_PROMO_DISMISSIBLE_MODALS:
        if not any(title_substr in el.label for el in elements):
            continue
        button_lc = button_text.lower()
        button_seen = any(
            el.clickable and el.label.strip().lower() == button_lc
            for el in elements
        )
        if button_seen:
            return (title_substr, button_text)
    return None
```

(Точная сигнатура и форма зеркалят `_tt_try_dismiss_post_switch_modal` из PR #70.)

### 3.3. AccountSwitcher method

```python
def _tt_dismiss_profile_promo_dialog(self, ui_xml: str, retap: int) -> bool:
    """[WP #106 — 2026-05-19] Detect and dismiss TT profile-tab promo-modal.

    Вызывается в `_switch_tiktok` retap-loop между `_tt_dismiss_security_prompt`
    и `_tt_is_own_profile`. Один dismiss/retap (cap).

    Kill-switch: env-var `TT_PROFILE_PROMO_DISMISS_DISABLED=1` → возврат False
    без detection.

    Returns:
        True если whitelist-match И tap прошёл успешно. Caller должен
        sleep + re-dump UI на основном пути.
        False если whitelist miss, kill-switch активен, или tap_element вернул False.
    """
    if os.environ.get('TT_PROFILE_PROMO_DISMISS_DISABLED') == '1':
        return False
    matched = _tt_try_dismiss_profile_promo(ui_xml)
    if matched is None:
        return False
    title_substr, button_text = matched
    self.p.log_event(
        'info', 'tt_profile_promo_dismiss_attempted',
        meta={'category': 'tt_profile_promo_dismiss_attempted',
              'title_substr': title_substr,
              'button_text': button_text,
              'retap': retap + 1,
              'platform': 'TikTok'},
    )
    tapped = self.p.tap_element(ui_xml, [button_text], clickable_only=True)
    if not tapped:
        self.p.log_event(
            'warning', 'tt_profile_promo_dismiss_tap_failed',
            meta={'category': 'tt_profile_promo_dismiss_tap_failed',
                  'title_substr': title_substr,
                  'button_text': button_text,
                  'retap': retap + 1,
                  'platform': 'TikTok'},
        )
        return False
    return True
```

### 3.4. Integration site

В `_switch_tiktok` retap-loop, line ~2326-2335:

```python
# EXISTING
if self._tt_dismiss_security_prompt(xml_probe):
    self.p.log_event('account_switch',
                     f'tt_security_prompt_dismissed step=tt_2_profile_tab retap={retap+1}',
                     meta={'category': 'tt_security_prompt_dismissed',
                           'retap': retap + 1,
                           'platform': 'TikTok'})
    time.sleep(POST_TAP_WAIT_S + 0.5)
    xml_probe = self.p.dump_ui(retries=3) or ''

# NEW (WP #106): profile-tab promo-modal dismiss (вторая ступень)
if self._tt_dismiss_profile_promo_dialog(xml_probe, retap=retap):
    time.sleep(POST_TAP_WAIT_S + 0.5)
    xml_probe = self.p.dump_ui(retries=3) or ''

# EXISTING
if self._tt_is_own_profile(xml_probe):
    ...
```

Два блока независимы и могут оба сработать в одной итерации (security_sheet и promo одновременно — теоретически да, но крайне маловероятно; cap=1 на каждый из них, sleep+re-dump между).

### 3.5. Observability — emitted events

| event_name | type | when |
|---|---|---|
| `tt_profile_promo_dismiss_attempted` | info | matched whitelist, перед tap_element |
| `tt_profile_promo_dismiss_tap_failed` | warning | matched, но tap_element вернул False |
| (existing) `own_profile_ok step=tt_2_profile_tab retap={retap}` | info | если break случился ПОСЛЕ нашего dismiss — observable через retap-idx |
| (existing) `not_own_profile step=tt_2_profile_tab retap={retap+1}` | error/info | если dismiss не помог |

Дополнительный `_recovered`-event НЕ добавляем (избыточен, существующий `own_profile_ok` уже информативен по retap-idx).

Никакого нового `error_code`. Фейл-путь без изменений: `tt_2_not_own_profile` → `tt_profile_tab_broken`.

### 3.6. Kill-switch

`os.environ.get('TT_PROFILE_PROMO_DISMISS_DISABLED') == '1'` — выставляется на VPS без редеплоя:

```bash
pm2 set autowarm:env.TT_PROFILE_PROMO_DISMISS_DISABLED 1 && pm2 restart autowarm
```

(Точное имя env-канала pm2 уточним при деплое; в коде проверка через `os.environ`.)

## 4. Test plan

Новый файл `tests/test_account_switcher_profile_promo_dismiss.py`:

### 4.1. Unit (helper `_tt_try_dismiss_profile_promo`) — 6 тестов

| test | input | expected |
|---|---|---|
| `test_match_contacts_promo` | `tt_profile_promo_contacts_7827.xml` | `('Чтобы связаться в TikTok', 'Не разрешать')` |
| `test_match_fb_friends_promo` | `tt_profile_promo_fb_friends_7870.xml` | `('Разрешить TikTok доступ к списку ваших друзей', 'Не разрешать')` |
| `test_no_match_security_sheet` | существующая фикстура «Быстрая проверка безопасности» | `None` (за пределами whitelist promo) |
| `test_no_match_other_dialog_with_disallow` | синтетический XML: «Что-то совсем другое» + clickable «Не разрешать» | `None` (защита от false-tap) |
| `test_no_match_title_present_button_not_clickable` | синтетический XML: title есть, button есть но `clickable=false` | `None` |
| `test_empty_xml` | `""` | `None` |
| `test_malformed_xml` | `"<garbage>"` | `None` (parse_ui_dump возвращает `[]` на parse error → guard `if not elements`) |

### 4.2. Method (`_tt_dismiss_profile_promo_dialog`) — 3 теста

Через `FakePublisher` (как в `test_account_switcher_modal_dismiss.py`):

| test | scenario | expected |
|---|---|---|
| `test_match_emits_event_and_taps` | contacts promo dump | True + `tt_profile_promo_dismiss_attempted` event + `tap_element` вызван с `['Не разрешать']` |
| `test_no_match_returns_false_no_events` | other dialog | False + 0 events |
| `test_kill_switch_disabled` | env `TT_PROFILE_PROMO_DISMISS_DISABLED=1`, contacts dump | False + 0 events + 0 detection runs |

### 4.3. Integration (через `FakePublisher` стенд `_switch_tiktok`) — 2 теста

Шаблон тот же что `tests/test_account_switcher_modal_dismiss.py::TestPostSwitchModalIntegration`:

| test | scenario | expected |
|---|---|---|
| `test_retap1_promo_dismissed_then_own_profile` | retap1 dump = contacts promo; retap1 re-dump = own_profile | switch success, break после retap1, emitted `tt_profile_promo_dismiss_attempted` + `own_profile_ok step=tt_2_profile_tab retap=1` |
| `test_all_3_retaps_promo_persists_then_fail` | retap1/2/3 dump = contacts promo; re-dump после каждого dismiss остаётся promo (модалка возвращается / TT капризничает) | switch fail с `step=tt_2_not_own_profile`, 3 emitted `_attempted` events, 0 own_profile_ok |

### 4.4. Fixtures

Скачиваем из S3 (один раз) в `tests/fixtures/`:
- `tt_profile_promo_contacts_7827.xml` ← `https://save.gengo.io/autowarm/ui_dumps/tiktok/task7827_switch_7827_tt_2_not_own_retap1_1779182029.xml`
- `tt_profile_promo_fb_friends_7870.xml` ← `https://save.gengo.io/autowarm/ui_dumps/tiktok/task7870_switch_7870_tt_2_not_own_retap1_1779185960.xml`

(Уже скачаны для триажа в `/tmp/tt-triage-2026-05-19/`.)

### 4.5. Regression — full switcher suite

`pytest tests/test_account_switcher*.py -v` — 0 новых регрессий.

## 5. Deploy

1. PR в `GenGo2/delivery-contenthunter` (worktree `worktree-wt-wp106-tt-promo-dismiss`).
2. Merge → auto-push hook в `/root/.openclaw/workspace-genri/autowarm/` (per memory `reference_autowarm_git_hook`).
3. `pm2 restart autowarm`.
4. **Post-deploy smoke**: re-queue 1 из 4 сегодняшних тасок (например 7884) через UPDATE publish_queue → pending. Ожидаем `tt_profile_promo_dismiss_attempted` event + `tt_2_not_own_profile` пропадает.
5. **24h soak**: monitor `error_code='tt_profile_tab_broken'` count → ожидаем падение с 3-7/день до ~0 (или явное обнаружение нового variant'а модалки в логах через `not_own_profile` без preceding `dismiss_attempted` — расширим whitelist).

## 6. Risks & mitigations

| risk | likelihood | mitigation |
|---|---|---|
| Ложный tap «Не разрешать» в неродственном контексте | low | Title-substring match обязателен. `'Чтобы связаться в TikTok'` и `'Разрешить TikTok доступ к списку ваших друзей'` — уникальные строки в TT UI. |
| Модалка не закрывается даже после tap (TT bug / overlay) | medium | Existing retap-loop отрабатывает: на retap2/3 пробуем снова. После 3 неудач — fail как и сейчас, без зацикливания. |
| Появление нового variant'а модалки → false-negative | medium | Observability `not_own_profile` без preceding `dismiss_attempted` — сигнал расширить whitelist. Whitelist расширяется одной строкой без рефактора. |
| `tap_element` не находит кнопку (например, координаты съехали) | low | Existing `tap_element` импл проверена в PR #70. Если возвращает False — emits `_tap_failed` warning, retap-loop продолжает. |
| Regression в `_tt_dismiss_security_prompt` | very low | Не трогаем существующий код, добавляем новый блок ниже. |
| Парсинг УП-дампа с promo обнаружит элемент с substring `'Чтобы связаться в TikTok'` в каком-то другом контексте | very low | Strings достаточно специфичны (не overlap с другими TT screens). Дополнительно требуется clickable button «Не разрешать» — двойной match. |

## 7. Out of scope

- EN-варианты модалок (нет evidence сейчас, добавляются по той же схеме).
- Другие probe-сайты вне `_switch_tiktok` retap-loop (PR #70 уже покрыл post-switch).
- Vision-based recovery (избыточен для текстового UI).
- Изменение фейл-пути `error_code` — остаётся `tt_profile_tab_broken`.

## 8. Файлы, которые изменяем

- `account_switcher.py` — добавляем 1 constant, 1 module helper, 1 method, 1 блок в `_switch_tiktok` retap-loop. Не трогаем существующий security_prompt путь.
- `tests/test_account_switcher_profile_promo_dismiss.py` — новый, ~150 строк.
- `tests/fixtures/tt_profile_promo_contacts_7827.xml` — новый.
- `tests/fixtures/tt_profile_promo_fb_friends_7870.xml` — новый.

## 9. Acceptance

- [ ] Все новые тесты проходят (~11 шт.).
- [ ] `pytest tests/test_account_switcher*.py` — 0 регрессий относительно baseline `main`.
- [ ] Codex review (full diff) — 0 P1.
- [ ] Post-deploy smoke на re-queue одной задачи 2026-05-19 — switch проходит.
- [ ] 7-day soak: `tt_profile_tab_broken` падает к ~0 или явно идентифицирован новый variant в логах.
