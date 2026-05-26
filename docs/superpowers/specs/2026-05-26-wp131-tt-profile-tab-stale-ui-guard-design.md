# Design — WP #131: TT `tt_profile_tab_broken` — stale-uiautomator guard в own-profile верификации

**WP:** https://openproject.contenthunter.ru/wp/131
**Категория:** `tt_profile_tab_broken` (внутренний шаг `tt_2_not_own_profile`)
**Статус:** разведка завершена (Path 1 выбран пользователем 2026-05-26). Это **отдельная** WP, не дубль #130.
**Связанные спеки:** [WP #105 dumpsys-trust-on-stale-ui](2026-05-22-wp105-dumpsys-trust-on-stale-ui-design.md), [WP #130 TT foreground-guard], [WP #106 TT profile promo dismiss].

## 1. Свежие прод-данные (после деплоя #130 22.05)

`tt_profile_tab_broken` по дням (`error_code`, platform=TikTok, status=failed):

| Дата | Фейлов | Объём TT/день |
|---|---|---|
| 2026-05-18 | 7 | норм |
| 2026-05-19 | 6 | норм |
| 2026-05-20 | 3 | 76 |
| 2026-05-21 | 3 | 78 |
| 2026-05-22 | 2 | 85 ← деплой #130 |
| 2026-05-23 | 1 | 17 (низкий) |
| 2026-05-24 | 0 | 5 (очень низкий) |
| **2026-05-25** | **3** | 61 |
| **2026-05-26** | **2** | частичный день |

**Вывод:** #130 НЕ поглотил #131. Категория держится на baseline ~2-3/день и после деплоя. `24.05=0` обманчив (всего 5 TT-задач за день). Опция «закрыть как дубль #130» отклонена.

Для приоритизации: `tt_profile_tab_broken` = 6 за 23-26.05; топ-TT-фейлы сейчас — `phone_or_email_link_required` (32) и `tt_account_not_in_list` (20). Этот фикс — не самая крупная TT-рыба, но категория стабильна и имеет чистый root cause.

## 2. Root cause (по 5 свежим post-#130 фейлам + UI-дампам)

`tt_profile_tab_broken` — **catch-all терминал**, ловящий ≥3 разные первопричины. По дампам на шаге `tt_2_profile_tab` (save.gengo.io):

| task | устройство | экран в дампе | первопричина |
|---|---|---|---|
| 9871 | RF8YA0HBR4B | лаунчер, но `dumpsys=com.zhiliaoapp.musically` + `trusted_dumpsys (stale UI)` ×N | **stale uiautomator** |
| 9822 | RF8YA0V5TAH | то же (`trusted_dumpsys` ×5, `pkg_disagree` ×5) | **stale uiautomator** |
| 9616 | RF8YA09S90H | `recovery launcher attempt=1 → foregrounded attempt=2`, финал stale | drift+stale (#130 recovery сработал, верификация на stale) |
| 9648 | RF8Y80ZV1WF | TikTok fg + модалка «История просмотров» (`viewer_auth_switch`/«Сохранить») | блокирующая модалка (out of scope) |
| 9652 | RFGYB180RZV | TikTok fg + «Вы вышли из аккаунта. Попробуйте войти снова.»/«OK» | аккаунт разлогинен (out of scope) |

### Механизм доминирующего bucket'а (stale uiautomator) — подтверждён по коду

Retap-петля (`account_switcher.py:2732-2909`) на каждой итерации берёт `xml_probe = self.p.dump_ui(retries=3)` и гоняет 4 детектора: `_tt_is_own_profile` / `_tt_is_logged_out` / `_tt_is_reauth_prompt` / `_tt_is_foreign_profile`. Когда uiautomator **залип** и отдаёт XML лаунчера:

- `dumpsys` стабильно говорит `com.zhiliaoapp.musically` (TikTok реально на переднем плане — подтверждено событиями `switcher_foreground_trusted_dumpsys`);
- но `xml_probe` = протухший снимок лаунчера → **все 4 детектора → False** → fall-through в `not_own_profile` retap;
- `tt_bound_nav: tap_method=coords_fallback (no_bounds_in_xml)` — навигация тоже не находит bottom-nav в XML, тапает по координатам;
- `dump_ui(retries=3)` не спасает: ретраи против залипшего uiautomator остаются stale (WP #105: stale держится **минуты**, не секунду);
- 3 retap'а (включая `_tt_smart_tap_profile` и cold-start `force-stop`+`am start`) исчерпываются → `_fail(step='tt_2_not_own_profile')` → `error_code=tt_profile_tab_broken`.

По всем 14 фейлам с 20.05: `fg_recovery` отработал в 13/14, `coords_fallback (no_bounds_in_xml)` — в ~11/14 → дамп для верификации был неверным почти везде. **#130 (foreground) в основном работает; маркеры own-profile НЕ сломаны** — проблема в том, что верификация читает протухший XML.

### Почему «рестарт uiautomator» не вариант

WP #105 установил: **чистого shell-механизма перезапустить uiautomator нет**. Stale — это устаревшее window-окно в AccessibilityService при незавершённом транзишене, держится минутами. Поэтому фикс — **не пытаться добыть хороший XML**, а при подтверждённом stale-UI перестать доверять XML-вердикту own-profile и уйти в путь, где гейтом служит реальный downstream (editor-triggers) или vision.

## 3. Scope

**В скоупе (Path 1):** только **stale-uiautomator bucket** (9871/9822/9616) — доминирующий, чистый root cause.

**Вне скоупа (отдельные child-WP):**
- «История просмотров» (`viewer_auth_switch`) — блокирующая модалка → расширить whitelist `_tt_dismiss_profile_promo_dialog` (паттерн WP #67/#106).
- «Статус аккаунта / Вы вышли из аккаунта» — разлогин → новый детектор → terminal `tt_2_logged_out` / account_blocks (паттерн WP #93 `phone_or_email_link_required`).

Эти два — long-tail (по 1 из 5), заводятся как child-WP, не раздувают горячую зону в этом PR.

## 4. Design — stale-UI guard перед объявлением `not_own`

### 4.1 Детект stale-UI в точке own-profile probe

Новый helper (переиспользует stability-check WP #105):

```python
def _tt_dumpsys_confirms_foreground(self, target_pkg: str, reads: int = 3,
                                    interval: float = 0.5) -> bool:
    """True если dumpsys СТАБИЛЬНО (reads подряд) видит target_pkg на
    переднем плане. Дёшево, без uiautomator. Тот же приём, что
    _foreground_pkg trust-dumpsys ветка (WP #105)."""
    for _ in range(reads):
        top = self.p.adb("dumpsys activity activities | "
                         "grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
        m = re.search(r'\s([\w\.]+)/[\w\.]+', top)
        if (m.group(1) if m else '') != target_pkg:
            return False
        time.sleep(interval)
    return True
```

«Stale-UI на этой итерации» = `xml_probe` пустой ИЛИ его доминантный package = лаунчер (`com.sec.android.app.launcher`) И `_tt_dumpsys_confirms_foreground(cfg['package'])`.

### 4.2 Точка врезки — `break` из retap-петли при stale-UI (`~2856`)

> **Пересмотрено после Codex review round 1 (P1: wrong-account posting).**
> Первая версия предлагала `_tap_plus_and_verify(already_matched=True)` напрямую из guard'а. Codex справедливо указал: `editor_triggers` доказывают лишь что **редактор открылся**, но НЕ что мы на аккаунте `target`. На мульти-аккаунт устройстве при stale uiautomator это могло опубликовать под чужим аккаунтом. Отклоняем этот путь.

Ключ: проверка имени target-аккаунта **уже существует** сразу после retap-петли (`account_switcher.py:2911-2925`), и **с vision-fallback**:

```python
elements, source, _ = self._read_screen_hybrid('tt_2_profile_screen')
current = None
if source == 'uiautomator':
    current = get_current_account_from_profile(elements, header_y_max=...)
if not current:
    current = self._vision_read_current_account('tt_2_profile_screen')  # vision!
if current and current == target:
    return self._tap_plus_and_verify(..., already_matched=True)         # постим ТОЛЬКО при совпадении
# иначе → #130 fg-guard → _open_tt_account_switcher → переключить аккаунт
```

При stale uiautomator `get_current_account_from_profile` вернёт None (XML лаунчера), и сработает `_vision_read_current_account` — **скриншот при stale uiautomator корректен** (доказано WP #105: dumpsys+скриншот согласны, залипает только uiautomator XML). То есть существующий путь уже умеет читать аккаунт через vision и постит **только при `current == target`**, иначе уходит в bottomsheet-переключение.

**Проблема не в отсутствии проверки аккаунта — она есть. Проблема в том, что retap-петля исчерпывается и `_fail`-ит ДО того, как дойдёт до этой проверки.** Поэтому фикс — при подтверждённом stale-UI **`break` из петли** (а не `_fail`), чтобы управление дошло до vision-based account verification на 2911:

```python
# [WP #131] stale-uiautomator guard: dumpsys стабильно видит TikTok, но
# xml_probe — протухший лаунчер/пусто → все 4 детектора ложно-False.
# Не жжём retap'ы и НЕ _fail-им на stale XML: тапаем профиль-таб ещё раз
# (чтобы реальный экран был профилем, а не Feed — coords_fallback т.к.
# bottom-nav bounds в stale XML нет), settle, затем выходим из петли —
# отработает vision-based проверка target-аккаунта ниже (2911+), которая
# постит ТОЛЬКО при current==target, иначе → bottomsheet-переключение.
if _STALE_UI_OWN_PROFILE_GUARD and self._tt_probe_looks_stale(xml_probe) \
        and self._tt_dumpsys_confirms_foreground(cfg['package']):
    self.p.log_event(
        'account_switch',
        f'tt_own_profile_stale_ui: dumpsys=TikTok стабилен, uiautomator stale '
        f'(retap {retap+1}) → профиль-тап + break в vision account verify',
        meta={'category': 'tt_own_profile_stale_ui',
              'retap': retap + 1, 'platform': 'TikTok',
              'probe_pkg': self._dominant_pkg(xml_probe)})
    self._save_dump(f'tt_2_stale_ui_retap{retap+1}', xml_probe)
    # [Codex P2 round 2] Гарантируем профиль-таб ДО break: иначе при реальном
    # Feed/Search vision прочитает не-профиль → None. smart_tap (label) с
    # fallback на coords — тот же приём, что retap2.
    if not self._tt_smart_tap_profile():
        self._go_to_profile_tab(cfg, f'tt_2_stale_retap{retap+1}')
    time.sleep(POST_TAP_WAIT_S + 1)
    break  # → 2911: _read_screen_hybrid → vision account read → switch/verify
```

`break` выходит из `for retap`, минуя ветку `else` (exhaustion `_fail`), и управление переходит на 2911. Срабатывает на **первом** подтверждённом stale-UI (ретапы own-profile бесполезны — это проблема uiautomator, а не промаха тапа), но **профиль-тап всё равно делается** в guard'е перед выходом, поэтому vision на 2911 читает профиль, а не Feed. Напомним: один профиль-тап уже выполнен на 2718 до входа в петлю, guard добавляет ещё один свежий перед vision-read.

### 4.3 Почему target-аккаунт остаётся верифицированным (ответ на Codex P1)

После `break` именно существующий код решает судьбу:

1. **vision читает `current`** (скриншот корректен при stale uiautomator) → если `current == target` → постим. Аккаунт **подтверждён vision'ом**, не пропущен.
2. **vision читает другой аккаунт** (`current != target`) → НЕ постим: код уходит в `_open_tt_account_switcher` + `_find_and_tap_account(target)` → реально переключает на target, затем `_tap_plus_and_verify(already_matched=False)` (повторная верификация). Wrong-account posting исключён.
3. **vision вернул None** (не профиль / не прочитал) → `current` falsy → bottomsheet-путь (или честный `tt_3_*` fail). Тоже не постим вслепую.

Нигде после `break` нет публикации без подтверждения `current == target` (или явного переключения на target). Это **строго безопаснее** старого поведения (которое просто `_fail`-ило) и устраняет риск P1, не добавляя отдельный vision-вызов — переиспользуем уже существующий vision-fallback.

### 4.4 Что НЕ трогаем

- `_tt_guard_switcher_foreground` (#130) — корректен, recovery работает.
- 4 детектора own/logged_out/reauth/foreign — без изменений (маркеры не сломаны).
- WP #105 trust-dumpsys в `_foreground_pkg` — без изменений (переиспользуем приём, не правим).
- retap-эскалация (smart_tap, cold-start) — остаётся для НЕ-stale кейсов.

## 5. Kill-switch

```python
_STALE_UI_OWN_PROFILE_GUARD = os.getenv('TT_STALE_UI_OWN_PROFILE_GUARD', '1') != '0'
```

Default включён. `=0` → старое поведение (retap → fail). Мгновенный откат без передеплоя.

## 6. Наблюдаемость

Новое событие `tt_own_profile_stale_ui` (meta: retap, probe_pkg, platform). После деплоя за 24ч:
- частота нового пути (`break` по stale-UI);
- кросс-сверка task'ов с этим событием против финального статуса — если доходят до `done`/published (через `tt_fp_editor`) или корректного bottomsheet-переключения, это фактическое доказательство, что путь безопасен;
- если task с `tt_own_profile_stale_ui` падает дальше — теперь под **честным** downstream-step'ом (`tt_3_*` account-switcher / `tt_fp_editor`), а не под catch-all `tt_profile_tab_broken`. Сама по себе перемаркировка — уже улучшение триажа.

## 7. Тесты (`test_account_switcher.py`, fake-proxy)

| Сценарий | Ожидание |
|---|---|
| dumpsys=TikTok стабильно + xml=лаунчер + vision читает `current==target` | guard срабатывает (`break`), эмит `tt_own_profile_stale_ui`, vision-read подтверждает target → `_tap_plus_and_verify` (главный кейс) |
| **dumpsys=TikTok стабильно + xml=лаунчер + vision читает ДРУГОЙ аккаунт** | guard `break`, но `current != target` → **bottomsheet-переключение** (`_open_tt_account_switcher`/`_find_and_tap_account`), НЕ постит напрямую (ответ на Codex P1) |
| dumpsys=TikTok стабильно + xml=лаунчер + vision вернул None | guard `break`, `current` falsy → bottomsheet-путь / честный `tt_3_*` fail, не постит вслепую |
| stale-UI + реальный экран Feed (не профиль) | guard делает `_tt_smart_tap_profile`/`_go_to_profile_tab` ПЕРЕД `break` → vision на 2911 читает профиль, а не Feed (Codex P2 round 2). Ассертим, что профиль-тап вызван до выхода. |
| xml=лаунчер, но dumpsys нестабилен (TikTok→launcher→TikTok) | guard НЕ срабатывает → старый retap/fail (честный launcher) |
| xml=own-profile сразу | success, guard не достигается |
| xml=foreign (Подписаться/Сообщение) | старый foreign-probe путь, guard не трогает |
| xml=пусто + dumpsys=TikTok стабилен + vision==target | guard срабатывает (пустой dump = stale) → vision подтверждает → post |
| kill-switch=0 + dumpsys=TikTok + xml=лаунчер | guard выключен → старый retap/fail |

Перед написанием тестов сверить имена методов fake-proxy с реальным `DevicePublisher` / `AccountSwitcher` (`adb`, `dump_ui`, `log_event`, `_read_screen_hybrid`, `_vision_read_current_account`, `_open_tt_account_switcher`) — анти-дрейф (урок PR #52). Ключевой тест — wrong-account: vision возвращает аккаунт ≠ target, ассертим что публикация НЕ происходит, а идёт переключение.

## 8. Деплой

- Python-публикатор спавнится свежим на каждую задачу → **PM2 restart не нужен**.
- Раскатка: cherry-pick фикса в prod autowarm (`/root/.openclaw/workspace-genri/autowarm/`).
- Перед отдачей пользователю — `codex review` спека → плана → диффа, раундами до 0 P1/P2 (стандартная практика).
- Проверка на проде за 24ч: query `tt_own_profile_stale_ui` + динамика `tt_profile_tab_broken` (цель — к нулю в stale-bucket).
- Worktree + atomic commit + зелёный pytest перед merge (parallel-sessions practice).

## 9. Риски

| Риск | Митигация |
|---|---|
| **Wrong-account posting** (TikTok fg, но на чужом аккаунте; uiautomator stale) | `break` НЕ постит — управление идёт на 2911 vision-based account read; публикация только при `current==target`, иначе bottomsheet-переключение на target. (Codex P1 round 1 — устранено в §4.2-4.3.) |
| dumpsys врёт (TikTok крашнулся, topResumedActivity устарел) → guard зря сработал | Стабильность-чек (3×0.5с) отсекает блипы. Даже если сработал: vision-read на 2911 не найдёт профиль/аккаунт → bottomsheet/честный fail, не ложная публикация. |
| Guard маскирует genuine «не на профиле» (feed/чужой экран) | Срабатывает только при xml∈{лаунчер,пусто} И стабильном dumpsys=TikTok. Guard делает профиль-тап ПЕРЕД `break` (Codex P2), foreign-profile (anti-markers) идёт прежним путём, модалки (viewer-history/logged-out) — не лаунчер, не маскируются. После `break` vision-read всё равно верифицирует аккаунт. |
| vision сам ненадёжен при stale | Скриншот ≠ uiautomator: WP #105 доказал, что при stale uiautomator скриншот корректен. Если vision всё же вернёт None → bottomsheet/честный fail (не публикация). |
| Параллельные сессии правят `_switch_tiktok` | Worktree + atomic commit + зелёный pytest перед merge. |

## 10. Связанные сущности

- WP #130 (PR #97, `486fec2`) — TT foreground-guard; #131 — отдельный downstream-баг, не дубль.
- WP #105 (dumpsys-trust-on-stale-ui) — источник stability-check приёма; #131 распространяет его на own-profile верификацию.
- WP #106 / #67 — TT promo/modal dismiss — паттерн для out-of-scope «История просмотров».
- WP #93 (`phone_or_email_link_required`) — паттерн для out-of-scope разлогина.
