# WP #180 — YT stale uiautomator на профиле

**Дата:** 2026-05-28
**OpenProject:** https://openproject.contenthunter.ru/wp/180
**Тип:** Ошибка (Bug)
**Статус:** Бэклог → готов к плану
**Owner:** Данил Павлов
**Сессия:** Claude (Opus 4.7), ветка `wp/yt-triage-2026-05-28`

## Проблема

За 28.05.2026 YouTube — **13 фейлов**, из них **9 (69 %) — `yt_accounts_btn_missing_postmortem`**. За **14 дней — 91 фейл** этого кода на 5 устройствах и 9 аккаунтах (не device-specific).

**Фактическая причина — stale uiautomator на YT-профиле**, не «кнопка Аккаунты исчезла». В events 9/9 sample-задач (11429/11430/11431/11535/11544/11553/11627/11639/11661):

```
yt_0_foreground_guard  usable=True  bytes=24675   ← живой dump (YT впереди)
yt_1_feed              usable=True  bytes=24675   ← живой
yt_1_dismiss           usable=False bytes=4936    ← stale начинается
yt_2_profile_screen    usable=False bytes=4936    ← stale
yt_3_pre_tap           usable=True  bytes=24675   (иногда удаётся, иногда 4936)
yt_3_retap_probe1      usable=False bytes=4936
yt_3_retap_probe2      usable=False bytes=4936
yt_3_alt_avatar_probe  usable=False bytes=4936
yt_3_open_accounts_postmortem  usable=False bytes=4936
→ yt_accounts_btn_missing_postmortem (ЛОЖНО)
→ T9 yt_settings_activity_fallback_start → тоже падает (читает stale dumps)
→ yt_picker_failed_to_open
```

`bytes=4936` — известная сигнатура `is_dump_usable=False` (та же, что в WP#131 для TT и WP#105 для IG): пакет на переднем плане, но uiautomator не видит view-tree (Compose/SurfaceView/FLAG_SECURE-окно).

`_yt_try_accounts_btn_with_retries` (`account_switcher.py:4405`) видит пустые elements, ни один trigger не матчится — 2 retap'а, alt-avatar и T9 Settings-Activity жгутся впустую и заканчиваются ложным postmortem'ом.

Триаж и evidence: [`docs/evidence/2026-05-28-yt-triage.md`](../evidence/2026-05-28-yt-triage.md).

## Прецеденты

* **WP #131 / WP #164 (TT)** — `_tt_probe_looks_stale` + `_tt_dumpsys_confirms_foreground` + honest emit `tt_own_profile_stale_ui` под kill-switch `TT_STALE_UI_OWN_PROFILE_GUARD` (default ON). Реализовано в `account_switcher.py:2781, 2801, 3124-3149, 330-335`. SHIPPED+DEPLOYED 27.05.
* **WP #105 (IG)** — доверие dumpsys'у при залипшем uiautomator, kill-switch `SWITCHER_TRUST_DUMPSYS_ON_STALE_UI`.

На YT тот же паттерн не закрыт. Этот WP — точное зеркало WP #131 для YouTube.

## Цель

1. Перестать ложно атрибутировать stale-UI как «кнопка Аккаунты не найдена».
2. Перестать жечь 2 retap'а + alt-avatar + Settings-Activity на стайл-дампах.
3. Эмитить честный `yt_own_profile_stale_ui` с возможностью recovery через cold-restart YT.

**Что НЕ делаем:**
* НЕ трогаем `_yt_open_via_settings_activity` (T9). Это fallback для не-stale случаев («кнопка реально не найдена»). Если он будет фейлиться отдельно — будущий WP.
* НЕ трогаем single-account fastpath (`account_switcher.py:3666-3678`). Stale-guard уходит ПОСЛЕ SA-shortcircuit (SA пропускает поиск кнопки «Аккаунты» вообще).
* НЕ трогаем picker-side stale (после открытия picker'а) — другой класс, не доминанта.
* НЕ повышаем тайминги в `_read_screen_hybrid` — поведение остаётся прежним для всех остальных платформ/шагов.

## Архитектура

### Хелперы (новые, на уровне класса `AccountSwitcher`)

#### `_yt_probe_looks_stale(xml: str, target_pkg: str) -> bool`

Возвращает `True`, если dump «протух»:
* `xml` пустой / None, ИЛИ
* `target_pkg` (`com.google.android.youtube` по умолчанию из cfg) не присутствует в `xml`, ИЛИ
* `is_dump_usable(parse_ui_dump(xml)) == False`.

Иначе — `False`. Зеркало `_tt_probe_looks_stale` (`account_switcher.py:2781`).

#### `_yt_dumpsys_confirms_foreground(target_pkg: str, reads: int = 2, interval: float = 0.5) -> bool`

Стабильное чтение `dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'` `reads` раз подряд видит `target_pkg`. Если хоть раз пакет другой — `False`. Цена низкая (одна shell-команда без uiautomator).

Зеркало `_tt_dumpsys_confirms_foreground` (`account_switcher.py:2801`).

#### `_yt_stale_ui_check_and_recover(self, cfg: dict) -> Tuple[bool, str]`

Возвращает `(ok, status)`:
* `(True, 'no_stale')` — `_last_hybrid_xml` не выглядит stale → ничего не делаем, основной flow продолжается.
* `(True, 'recovered')` — был stale, dumpsys подтвердил YT, cold-restart выполнен, повторный dump usable.
* `(False, 'unrecoverable')` — stale + dumpsys=YT, но cold-restart НЕ помог (повторный dump снова stale) → caller обязан `_fail` с честным кодом `yt_own_profile_stale_ui`.
* `(True, 'not_yt_foreground')` — stale, но dumpsys НЕ подтверждает YT впереди → это другой класс (fg-drift); `yt_ensure_foreground` уже должен был это поймать выше, но defensive: возвращаем True, чтобы основной flow продолжился. (Если он упадёт по другому коду — это правильно.)

Логика:
```
xml = self._last_hybrid_xml or ''
if not _yt_probe_looks_stale(xml, cfg['package']):
    return (True, 'no_stale')

if not self._yt_dumpsys_confirms_foreground(cfg['package']):
    # fg-drift, не stale — отдаём обратно в обычный flow
    return (True, 'not_yt_foreground')

# stale + YT впереди → cold-restart
self.p.log_event(
    'account_switch',
    f'yt_own_profile_stale_ui_detected: cold-restart YT (variant={variant})',
    meta={'category': 'yt_own_profile_stale_detected',
          'variant': variant,                # opaque_hierarchy / launcher_empty / pkg_missing
          'step': 'yt_3_stale_recovery',
          'platform': 'YouTube'},
)
self._save_dump('yt_3_stale_dump', xml)

self.p.adb(f'am force-stop {cfg["package"]}')
time.sleep(POST_TAP_WAIT_S)
self._open_app_aggressive(
    cfg['package'], cfg['launch_activity'],
    step_name='yt_3_stale_recovery_relaunch', deadline_s=30.0,
)
time.sleep(POST_TAP_WAIT_S + 1)
self._go_to_profile_tab(cfg, 'yt_3_stale_recovery_profile')
time.sleep(POST_TAP_WAIT_S + 1)

elements_after, _, _ = self._read_screen_hybrid('yt_3_stale_recovery_probe')
if elements_after and is_dump_usable(elements_after):
    self.p.log_event(
        'account_switch',
        'yt_own_profile_stale_recovered',
        meta={'category': 'yt_own_profile_stale_recovered',
              'platform': 'YouTube'},
    )
    return (True, 'recovered')

self.p.log_event(
    'error',
    'yt_own_profile_stale_ui: cold-restart не помог, uiautomator всё ещё stale',
    meta={'category': 'yt_own_profile_stale_ui',
          'variant': variant,
          'step': 'yt_3_own_profile_stale_ui',
          'platform': 'YouTube'},
)
return (False, 'unrecoverable')
```

Где `variant`:
* `pkg_missing` — пакет YT отсутствует в xml (лаунчер/пустой XML);
* `opaque_hierarchy` — пакет есть, но `is_dump_usable=False`;
* `launcher_empty` — пустой XML без признаков пакета.

#### `_yt_stale_ui_guard_enabled() -> bool` (модульная функция)

```python
def _yt_stale_ui_guard_enabled() -> bool:
    """[WP #180] Kill-switch для stale-uiautomator guard на YT профиле."""
    return os.environ.get('YT_STALE_UI_OWN_PROFILE_GUARD', '1') != '0'
```

Default ON. `YT_STALE_UI_OWN_PROFILE_GUARD=0` → legacy: старый путь, как сейчас. Зеркало `_tt_stale_ui_guard_enabled` (`account_switcher.py:330-335`).

### Точка встройки в `_switch_youtube`

В `account_switcher.py` около строк 3691-3699, ПОСЛЕ fg-guard'а и refresh dump'а:

```python
# текущий код (3691-3699):
elements_refreshed, _, _ = self._read_screen_hybrid('yt_3_pre_tap')
if elements_refreshed:
    elements = elements_refreshed

# === NEW (WP #180): stale-UI guard перед retry-mill'ом ===
if _yt_stale_ui_guard_enabled():
    ok, status = self._yt_stale_ui_check_and_recover(cfg)
    if not ok:
        return self._fail(
            'uiautomator на YT-профиле залип (stale) — cold-restart не помог',
            step='yt_3_own_profile_stale_ui',
        )
    if status == 'recovered':
        elements_after, _, _ = self._read_screen_hybrid('yt_3_pre_tap_after_recovery')
        if elements_after:
            elements = elements_after
# === END NEW ===

_accts_result = self._yt_try_accounts_btn_with_retries(elements, cfg)
```

Финальный шаг `yt_3_own_profile_stale_ui` добавляется в `_SWITCHER_STEP_TO_CATEGORY` в `publisher_kernel.py:102` рядом с существующими YT-entries (~строки 162-172):

```python
'yt_3_own_profile_stale_ui': 'yt_own_profile_stale_ui',  # WP #180
```

Так финальный `error_code` через `_resolve_publish_fail_category()` корректно станет `yt_own_profile_stale_ui` (а не unknown / yt_accounts_btn_missing).

### Не трогаем

* `_yt_try_accounts_btn_with_retries` — оставляем как есть. Если recovery успел, дамп уже live; если не успел, мы уже вернули `_fail` выше.
* Все остальные ветки `_switch_youtube` (SA-shortcircuit, T9, picker scroll и т.д.).
* IG/TT/общие хелперы — без изменений.

## Data Flow

```
_switch_youtube
  → yt_0_foreground_guard            (existing)
  → yt_1_feed → yt_1_dismiss         (existing)
  → yt_2_profile_screen              (existing)
  → SA-shortcircuit?                  → (existing, exits)
  → yt_3_fg_guard                    (existing)
  → yt_3_pre_tap                     (existing)
  → [NEW] _yt_stale_ui_check_and_recover(cfg)
      ├─ no_stale       → continue
      ├─ not_yt_foreground → continue (defensive)
      ├─ recovered      → re-read elements, continue
      └─ unrecoverable  → _fail(yt_3_own_profile_stale_ui)  ★ HONEST EMIT
  → _yt_try_accounts_btn_with_retries  (existing)
  → ...
```

## Tests (TDD)

Тестовый файл: `tests/test_account_switcher_yt_stale_ui.py` (новый). Стиль и фикстуры — точно как в существующем `tests/test_account_switcher_tt_stale_ui.py` (зеркало WP #131): импорт `AccountSwitcher`, `_FakeProxy`, mock `_read_screen_hybrid` / `adb` / `_last_hybrid_xml`, `monkeypatch.setenv('YT_STALE_UI_OWN_PROFILE_GUARD', '0' or '1')`.

### Unit-tests (хелперы)

1. **`test_yt_probe_looks_stale_empty_xml`** — `_yt_probe_looks_stale('', 'com.google.android.youtube')` → `True`.
2. **`test_yt_probe_looks_stale_pkg_missing`** — XML без YT-пакета → `True`.
3. **`test_yt_probe_looks_stale_opaque_hierarchy`** — XML с YT-пакетом, но `is_dump_usable=False` → `True`. (Фикстура — 4936-байтовый минимальный stub.)
4. **`test_yt_probe_looks_stale_normal_dump`** — нормальный YT-профиль XML → `False`.
5. **`test_yt_dumpsys_confirms_foreground_stable`** — mock `p.adb()` возвращает `topResumedActivity=com.google.android.youtube/...` 2 раза → `True`.
6. **`test_yt_dumpsys_confirms_foreground_drift`** — первый read YT, второй sbrowser → `False`.
7. **`test_yt_dumpsys_confirms_foreground_empty`** — mock возвращает пустую строку → `False`.

### Flow-tests (`_yt_stale_ui_check_and_recover` + `_switch_youtube`)

8. **`test_switch_youtube_stale_dump_recovered_via_cold_restart`** — mock `_last_hybrid_xml` = stale; `_yt_dumpsys_confirms_foreground` → True; после cold-restart `_read_screen_hybrid` возвращает живые elements → status=`recovered`, retap-mill вызывается; никакого `yt_accounts_btn_missing_postmortem`.
9. **`test_switch_youtube_stale_dump_irrecoverable_emits_honest_code`** — оба dump'а stale → `_fail` с `step='yt_3_own_profile_stale_ui'`, log_event с `category='yt_own_profile_stale_ui'`; `_yt_try_accounts_btn_with_retries` НЕ вызывается; `_yt_open_via_settings_activity` НЕ вызывается.
10. **`test_switch_youtube_no_stale_runs_legacy_path`** — usable dump → status=`no_stale`, retap-mill вызывается как раньше.
11. **`test_switch_youtube_stale_but_not_yt_foreground_falls_through`** — stale, но dumpsys видит sbrowser → status=`not_yt_foreground`, основной flow продолжается (упадёт по другому коду, не нашему).
12. **`test_kill_switch_disabled_skips_stale_guard`** — `YT_STALE_UI_OWN_PROFILE_GUARD=0` → guard не вызывается, поведение прежнее (postmortem).

### Coverage criteria

* Все 5 веток `_yt_stale_ui_check_and_recover` покрыты unit/flow-тестами.
* Kill-switch off-путь покрыт.
* Existing tests `test_switch_youtube_*` — должны остаться зелёными (defensive: новый guard включается только когда elements/xml уже выглядят stale; на usable dump'е это no-op).

## Метрики наблюдения

После деплоя в течение 24-48 ч:
* SQL: `error_code IN ('yt_own_profile_stale_ui','yt_accounts_btn_missing_postmortem')` сравнение counts по дням.
* Ожидание: `yt_accounts_btn_missing_postmortem` стремится к 0 (на этом устройстве/аккаунте — точно к 0); `yt_own_profile_stale_ui` появляется в той же группе, плюс `yt_own_profile_stale_recovered` info-эмиты (метрика «recovery rate»).
* Если recovery rate низкий (cold-restart обычно не помогает) — обсудить более агрессивный шаг (Settings-Activity intent в этом же WP отдельной итерацией, или эскалация на `account_blocks(manual_recovery_required)`).

## Kill-switch / rollback

* **Default = ON**: чтобы guard заработал в проде, достаточно деплоя кода. Никаких ENV-changes не требуется.
* **Чтобы выключить (rollback)**: добавить `YT_STALE_UI_OWN_PROFILE_GUARD=0` в `.env` прода и перезапустить воркер (или дождаться следующего спавна публикатора — `load_dotenv` подхватывает env на каждый спавн, см. практику WP #122).
* Никаких миграций БД. Schema unchanged.

## Implementation steps (для writing-plans)

1. **TDD-task #1** — добавить `_yt_probe_looks_stale` + `is_dump_usable`-импорт (если нужно); 4 unit-теста (1-4).
2. **TDD-task #2** — добавить `_yt_dumpsys_confirms_foreground`; 3 unit-теста (5-7).
3. **TDD-task #3** — добавить `_yt_stale_ui_guard_enabled` модульную функцию.
4. **TDD-task #4** — добавить `_yt_stale_ui_check_and_recover` + integration-тест на recovery happy-path (8).
5. **TDD-task #5** — добавить unrecoverable-ветку с honest emit (9) + проверка что mill не вызывается.
6. **TDD-task #6** — встроить вызов в `_switch_youtube` (точка 3691); тесты 10/11.
7. **TDD-task #7** — kill-switch off-path (12).
8. **Verification** — прогнать полный `pytest tests/` (или target-набор); должны остаться зелёными все existing TT/IG-тесты.
9. **Codex review** — `codex review` на diff, итерации до 0 P1.
10. **PR + auto-deploy** — мерж в `main` `autowarm-testbench` запускает git-hook auto-push в `GenGo2/delivery-contenthunter` (см. `reference_autowarm_git_hook`); далее pm2 restart воркера в проде (или подождать SIGHUP/load_dotenv для kill-switch'а, если флаг ставится на дефолт ON через код, restart не нужен).
11. **24-48h verify** — SQL по новым кодам.

## Риски и mitigation

| Риск | Mitigation |
|---|---|
| Cold-restart YT всегда фейлит (recovery rate 0 %) | Kill-switch OFF + следующая итерация: попробовать `am start ...Shell_SettingsActivity` после cold-restart. |
| Ложное срабатывание stale-guard'а на usable dump'е | `_yt_probe_looks_stale` строгий: only-if-not-usable. `_yt_dumpsys_confirms_foreground` отсечёт fg-drift. Тесты 4/10 покрывают normal flow. |
| Regression в существующих YT-тестах | Тесты 8-12 + полный прогон pytest до мержа. Codex review. |
| Конфликт с параллельной сессией (`feedback_parallel_claude_sessions`) | Работаем в отдельной ветке `feat/wp180-yt-stale-uiautomator` autowarm-testbench, без `--amend`, всегда проверяем `git branch --show-current` перед commit. Worktree contenthunter уже отдельный (`wp/yt-triage-2026-05-28`). |
| Длиннохвост других YT-кодов растёт после нашего фикса (28.05: published_no_url=3, прочие по 1) | НЕ trying to fix everything at once — этот WP только про доминанту. Длиннохвост наблюдаем; будет доминантой — новый WP. |

## Open questions (закрыты в этом раунде)

| Вопрос | Решение |
|---|---|
| Recovery стратегия? | Cold-restart YT + одна попытка (вариант A). |
| Точка встройки? | После yt_3_pre_tap, перед `_yt_try_accounts_btn_with_retries`. |
| Default kill-switch? | ON (`'1'`), зеркало TT_STALE_UI_OWN_PROFILE_GUARD. |
| Затронуть T9 (`_yt_open_via_settings_activity`)? | Нет, отдельный WP при необходимости. |
| Затронуть SA-fastpath? | Нет, он выходит выше точки встройки. |
| Picker-side stale? | Не в этом WP. |
