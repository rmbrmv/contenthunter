# YT create-menu foreground guard — design

**Date:** 2026-05-19
**WP:** OpenProject #87 «YT post-switch: tap «+» не открывает Create-menu (yt_create_menu_not_reached + yt_editor_not_reached)»
**Repo:** `GenGo2/delivery-contenthunter` (dev: `/home/claude-user/autowarm-testbench`, prod: `/root/.openclaw/workspace-genri/autowarm`)
**Status:** approved by user 2026-05-19

## Контекст

Триаж 2026-05-19 (см. `docs/evidence/2026-05-19-yt-publish-triage.md`): 35 из 39 YT публикаций упали с error_code `yt_create_menu_not_reached` (26) / `yt_editor_not_reached` (7). 24/25 fails сопровождаются warning'ом `yt_post_switch_handle_unknown` на шаге `yt_5_target_profile`.

В 6 из 6 проверенных UI dump'ах foreground на шаге `yt_6_create_menu` = `com.sec.android.app.launcher`, а на предыдущем шаге `yt_5_target_profile` = `com.google.android.youtube`. То есть YT теряет foreground между свич-verify и dump'ом create-меню.

Скачанный screencast task 7726 (frames на 250–258s — YT-профиль; 260s — лончер) показал точку перехода. Анализ `account_switcher.py:100`:

```python
'plus_button': {'coords': (540, 2320), 'desc': ['Создать', 'Create']},
```

На Samsung 1080×2340 (тестбенч + prod) y=2320 — это область **Samsung system navigation bar (HOME)**, а YT bottom-nav «+» — около y=2240. Когда `tap_element(['Создать', 'Create'])` ничего не находит, fallback `adb_tap(540, 2320)` нажимает HOME → YT в фон → лончер → strict_verify читает дамп лончера → fail с `yt_create_menu_not_reached`.

## Цель

Перестать терять foreground на шаге yt_6_create_menu и/или фейлить с маскарадом `yt_create_menu_not_reached`, если фактически YT не в фокусе. Снизить долю YT fails сегодняшнего паттерна с ≈74% → ожидаемо <10% (остаются accounts/devices без рабочего picker'а).

## Архитектура

Все изменения локализованы в одном модуле:

- `account_switcher.py` — YT cfg (1 строка) + метод `_tap_plus_and_verify` (3 локальных вставки).

Используются уже существующие хелперы того же класса: `_detect_foreground_pkg`, `_yt_ensure_foreground`, `_fail`, `self.p.log_event`, `self.p.tap_element`, `self.p.dump_ui`, `self.p.adb_tap`. Никаких новых модулей, ни новых таблиц БД, ни схема-миграций.

Изменение касается **только YT-ветки** (`strict_verify=True`). IG/TT call-sites (`strict_verify=False`) не затронуты — это явный invariant и проверяется тестами.

## Уровни защиты

### Layer A — корректные координаты «+» в YT cfg

`account_switcher.py:100`:

```python
# было
'plus_button': {'coords': (540, 2320), 'desc': ['Создать', 'Create']},
# становится
'plus_button': {'coords': (540, 2240), 'desc': ['Создать', 'Create']},
```

Обоснование выбора y=2240: YT bottom-nav «+» по центру на 1080×2340 ≈ y=2240 (по видео-evidence task 7726, кадр 257s, и по геометрии: ratio 2240/2340 ≈ 0.957 — внутри bottom-nav-полосы YT, выше system navbar HOME y=2317).

Изменение применяется ВСЕГДА (kill-switch его не покрывает), потому что (540, 2320) — точно сломанная координата.

### Layer B — отказ от тихого fallback на coords при strict_verify

В `_tap_plus_and_verify` (account_switcher.py:4156) меняется блок tap'а:

```python
# было
tapped = False
if ui:
    tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True)
if not tapped:
    log.debug(f'[switcher] {step_prefix}_plus: fallback coords {plus["coords"]}')
    self.p.adb_tap(*plus['coords'])

# становится
tapped = False
if ui:
    tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True)
if not tapped and strict_verify and _guard_enabled():
    # Layer B: tap_element промахнулся; не тапать вслепую coords.
    # Сначала попробовать восстановить YT foreground и повторить element-tap.
    if self._yt_ensure_foreground(cfg, f'{step_prefix}_pre_tap_fg_recovery'):
        ui_retry = self.p.dump_ui(retries=1)
        if ui_retry:
            tapped = self.p.tap_element(ui_retry, plus['desc'], clickable_only=True)
if not tapped:
    # Если и после recovery элемент не найден (или strict_verify=False — IG/TT
    # legacy-path) — fallback на координаты с явной observability.
    if strict_verify:
        self.p.log_event(
            'warning', 'yt_plus_button_element_missing_fallback',
            meta={'category': 'yt_plus_button_element_missing_fallback',
                  'step': f'{step_prefix}_plus',
                  'coords': list(plus['coords'])},
        )
    log.debug(f'[switcher] {step_prefix}_plus: fallback coords {plus["coords"]}')
    self.p.adb_tap(*plus['coords'])
```

Поведение:

- Если `tap_element` нашёл элемент → как раньше.
- (YT only) Если не нашёл → `_yt_ensure_foreground` восстанавливает фокус и пробуем element-tap ещё раз.
- Если и после этого не нашёл → fallback на (теперь безопасные) coords + warning для analytics. Это не fail — продолжаем pipeline, Layer C поймает дальнейшие проблемы.
- IG/TT (`strict_verify=False`) поведение **не меняется**: сразу fallback на coords, без warning, без recovery.

### Layer C — foreground guard ПОСЛЕ tap «+», ДО strict_verify

Вставка в `_tap_plus_and_verify` после `time.sleep(POST_TAP_WAIT_S + 1.0)`:

```python
time.sleep(POST_TAP_WAIT_S + 1.0)

if strict_verify and _guard_enabled():
    fg = self._detect_foreground_pkg()
    yt_pkg = cfg['package']
    if fg and fg != yt_pkg:
        self.p.log_event(
            'warning', 'yt_create_menu_app_not_foregrounded',
            meta={'category': 'yt_create_menu_app_not_foregrounded',
                  'step': final_step,
                  'foreground_pkg': fg,
                  'attempt': 1},
        )
        recovered = self._yt_ensure_foreground(
            cfg, f'{final_step}_post_tap_fg_recovery')
        if recovered:
            # Одна повторная попытка tap «+» по element (без рекурсии).
            ui_r = self.p.dump_ui(retries=1)
            retapped = False
            if ui_r:
                retapped = self.p.tap_element(
                    ui_r, plus['desc'], clickable_only=True)
            if not retapped:
                self.p.adb_tap(*plus['coords'])
            time.sleep(POST_TAP_WAIT_S + 1.0)
            # после повторного tap'а — обычная ветка save_dump + verify ниже.
        else:
            return self._fail(
                f'{final_step}: foreground={fg} после tap «+», '
                f'_yt_ensure_foreground recovery не помог',
                step=f'{final_step}_app_not_foregrounded',
            )

self._save_dump(final_step, self.p.dump_ui(retries=1))
# ... как раньше
```

Эффект:

- Если YT остался на переднем плане → guard ничего не делает (overhead = 1 `dump_ui` вызов ~150ms).
- Если YT свернулся → пытаемся восстановить и сделать tap ещё раз. Если recovery успешный — strict_verify дальше дочитает реальный YT-дамп.
- Если recovery невозможен → fail-fast с новым осмысленным error_code `yt_create_menu_app_not_foregrounded` (не маскарад `yt_create_menu_not_reached`).

### Layer D — kill-switch + observability

**Env-флаг** `YT_CREATE_MENU_GUARD_ENABLED` (default = `'1'` / on). Читается через хелпер:

```python
def _guard_enabled() -> bool:
    return os.environ.get('YT_CREATE_MENU_GUARD_ENABLED', '1') != '0'
```

Покрытие kill-switch'а:

- Layer A (coord fix) — **НЕ покрыт kill-switch'ом**, применяется всегда. Прежняя координата (540, 2320) гарантированно сломанная — нет смысла оставлять её как fallback.
- Layer B (fg-recovery перед fallback) — покрыт.
- Layer C (fg-guard после tap'а) — покрыт.

Установка `YT_CREATE_MENU_GUARD_ENABLED=0` в PM2 ecosystem откатывает поведение к legacy (Layer B/C off), Layer A остаётся.

**Новые meta.category** для analytics:

- `yt_plus_button_element_missing_fallback` — element-tap промахнулся, recovery либо не помог, либо пропущен; fallback на coords.
- `yt_create_menu_app_not_foregrounded` — после tap'а foreground ≠ YT.
- (Terminal error_code) `yt_create_menu_app_not_foregrounded` (тот же ключ как step) — fail когда recovery не помог.

Существующий `yt_create_menu_not_reached` остаётся: если foreground OK, но strict_verify не нашёл триггеров (другая причина — например, dialog/modal перекрыл create-menu).

## Тесты

Новый файл `tests/test_yt_create_menu_fg_guard.py`. Используется существующий fake-proxy паттерн (см. `tests/test_yt_create_menu_strict_verify.py`). Сценарии (6 штук):

1. **Layer B happy path** — `tap_element` False на первом ui, `_yt_ensure_foreground` True, второй `tap_element` True → tap done, нет fallback'а, нет warning'а.
2. **Layer B fallback path** — `tap_element` False оба раза → fallback на `adb_tap(540, 2240)` (НЕ 2320) + event `yt_plus_button_element_missing_fallback`.
3. **Layer C recovery success** — после tap'а `_detect_foreground_pkg` возвращает launcher, `_yt_ensure_foreground` True, второй tap → strict_verify на свежем YT-дампе видит триггеры → ok.
4. **Layer C recovery fail** — `_detect_foreground_pkg` launcher, `_yt_ensure_foreground` False → `_fail` со step `yt_6_create_menu_app_not_foregrounded` и event `yt_create_menu_app_not_foregrounded`.
5. **Kill-switch off** — `YT_CREATE_MENU_GUARD_ENABLED=0`: Layer B/C ветки не вызываются (мокируем `_yt_ensure_foreground` чтобы assert'нуть что он не call'ался). Layer A coord (540, 2240) применяется всегда.
6. **IG/TT regression-guard** — `strict_verify=False`, `tap_element` False → сразу `adb_tap` без recovery, без warning, без fg-check после tap'а. Layer B/C полностью обходятся.

Mock-proxy `_FakeProxy` (memory: [[feedback_mock_proxy_drift]]) должен иметь method-сигнатуры **1-в-1** как у `DevicePublisher`: `dump_ui`, `tap_element`, `adb_tap`, `log_event`, `adb`. Если в DevicePublisher есть kwargs (типа `clickable_only`, `retries`) — у fake тоже.

Существующие тесты `tests/test_yt_create_menu_strict_verify.py` и `tests/test_yt_post_switch_verify.py` должны остаться зелёными без правок (если падают — ломали ли мы legacy-flow, надо разобраться до merge).

## Deploy и smoke

1. PR в `GenGo2/delivery-contenthunter` из ветки `feat/yt-create-menu-fg-guard` (создаётся в worktree autowarm-testbench).
2. CI: pytest зелёный (memory: [[feedback_parallel_claude_sessions]]).
3. После merge в main → автопуш в prod (memory: [[reference_autowarm_git_hook]]).
4. PM2 restart autowarm (если требуется по deploy инструкции).
5. Live smoke: re-queue 3 свежих YT-fail задач (NOT all 35 — иначе нет контроля), мониторим events. Ожидаемые статусы для re-queued:
   - `done` + post_url not null — фикс работает.
   - `failed` + `yt_create_menu_app_not_foregrounded` — Layer C сработал, root cause подтверждён, но recovery не вытащил. Это значит проблема глубже (например, аккаунт без channel, ad takeover, OS popup); отдельный triage.
   - `failed` + `yt_create_menu_not_reached` — Layer A/B/C обошлись, но reality другая (например, dialog поверх create-menu). Идём в новый виток разведки.
6. Если 0/3 проходят — `YT_CREATE_MENU_GUARD_ENABLED=0` в ecosystem (Layer B/C off, Layer A сохраняется) и обратный анализ.

## Risk и rollback

- **Layer A risk**: координата (540, 2240) выбрана по конкретной модели Samsung 1080×2340. Другие резолюции (если testbench/prod расширится) могут сломаться. Mitigation: переменная testbench-only через ENV не нужна — все prod-устройства одной модели (Samsung A52); если расширим парк, координаты в cfg в любом случае надо переосмыслить (для всех платформ).
- **Layer B risk**: добавляет один extra `_yt_ensure_foreground` + `dump_ui` на каждом промахе tap_element. Стоимость: ~2-5 сек на промах. Только в YT-ветке.
- **Layer C risk**: добавляет `_detect_foreground_pkg` (один dump_ui + regex) на каждом успешном tap'е. Стоимость: ~150ms. Только в YT-ветке.
- **Mock drift**: тесты могут пройти, а live publish — нет (memory: [[feedback_mock_proxy_drift]]). Mitigation: обязательный live smoke на 3 re-queued задачах перед закрытием WP.
- **Rollback**: `YT_CREATE_MENU_GUARD_ENABLED=0` в PM2 ecosystem (Layer B/C off). Полный откат (включая Layer A) — git revert PR.

## Out of scope

- Изменение `yt_post_switch_handle_unknown` (warning остаётся info, не блокирующим). Память [[feedback_yt_post_switch_handle_unknown_precursor]] предполагает превратить его в recovery-точку, но это вторая итерация после того как мы убедимся что текущий фикс закрывает большинство fails. Если Layer C ловит большинство — handle_unknown сам по себе перестанет вести к fails.
- Tests фикс существующих stale тестов (memory: [[project_validator_stale_generate_description_tests]] — это другой репо).
- Изменения для IG/TT plus_button — IG/TT работают через другие call-sites без strict_verify.
- Server-side метрики / dashboards.

## Линки

- WP #87 https://openproject.contenthunter.ru/work_packages/87 (приоритет «Высокий», comment activity #281)
- Triage evidence: `docs/evidence/2026-05-19-yt-publish-triage.md`
- Related shipped: PR #68 (WP #80 — yt_editor_upload_timeout 3-layer guards), PR #72 (WP #74 — YT foreign-foreground guard), PR #75 (WP #93 — TT switch blocking modal)
- Code: `/home/claude-user/autowarm-testbench/account_switcher.py:100,3134,4156,3203,3278,3466`
