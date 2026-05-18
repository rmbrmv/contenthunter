# YT foreign-foreground guard — Round 2 для WP #74

**Дата:** 2026-05-18
**Связано:** OpenProject WP #74 («YT: публикация не доходит до галереи после account switch — `yt_gallery_no_video_candidate`»)
**Round 1 (shipped 2026-05-15):** PR [#64](https://github.com/GenGo2/delivery-contenthunter/pull/64) — `_normalize_yt_state_pre_upload` (force-stop + LAUNCHER + permission-tap) + Task B расширил permission-keys в `_select_gallery_video` + Task C добавил `topResumedActivity`/`mCurrentFocus` в fail-fast meta. Закрыло 2/2 исходных кейса (camera permission overlay, Shorts description sheet).
**Round 2 trigger:** Task 6899 (2026-05-18, axilorj_ewelry, raspberry 1) — `topResumedActivity = com.sec.android.app.samsungapps/.initialization.ForceLoginSamungAccountActivity`. Force-stop YT не лечит чужой пакет.

---

## 1. Цели и нон-цели

### Цель

Закрыть рецидив `yt_gallery_no_video_candidate` класса «чужое приложение (Samsung Account ForceLogin и аналоги) перехватило foreground после `_normalize_yt_state_pre_upload`». Конкретно — выкатить foreign-foreground guard с escalation Skip→BACK→force-stop+relaunch, который ловит топ-активность ВНЕ allowlist YT/permission-controller, пытается её сбросить и возвращает YT на передний план.

### В scope

- Хелпер `_dismiss_foreign_foreground` в `publisher_youtube.py` (методом `YouTubeMixin`).
- Два checkpoint'а:
  1. Хвост `_normalize_yt_state_pre_upload`.
  2. Перед fail-fast в `_select_gallery_video` (с 1 retry probe gallery после успешного recovery).
- Расширение fail-fast meta: `meta.foreign_foreground_*` поля. Зонтичная категория `yt_gallery_no_video_candidate` СОХРАНЯЕТСЯ — дашборды не ломаются.
- Env-flag kill-switch `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` (паттерн из WP #82).
- Unit-тесты в новом файле `tests/test_publisher_youtube_foreign_foreground.py` + интеграционные ассерты в `test_publisher_youtube_state_normalize.py` и `test_publisher_youtube_picker.py`.
- Live smoke на autowarm-testbench перед merge.

### Вне scope

- IG/TT foreign-foreground guard (отдельный backlog, если поймают аналог).
- Per-step continuous guard на каждом Шаге 1–7 publish_youtube_short.
- Изменение `_ensure_correct_account` и Шагов 1–5, 7 publish_youtube_short.
- Новый top-level `error_code` (умбрелла `yt_gallery_no_video_candidate` остаётся per memory `feedback_publisher_error_code_misleading`).
- Изменения analytics dashboards.

---

## 2. Архитектура / границы / allowlist

### Сигнатура

```python
def _dismiss_foreign_foreground(self, *, source: str, allow_recovery: bool = True) -> dict:
    """
    Args:
      source: откуда вызван ('post_normalize' | 'pre_gallery_select_fail_fast')
              — идёт в meta для триажа.
      allow_recovery: False → только detect+report, никаких BACK/force-stop.
                      Используется в kill-switch / dry-run сценариях.
    Returns dict:
      {
        'foreign_detected': bool,
        'top_package': str | None,
        'top_activity': str | None,
        'recovered': bool,
        'escalation_steps': list[str],  # подмножество ['skip_tap','back_x1','back_x2','force_stop_and_relaunch']
        'unrecoverable_reason': str | None,
          # None | 'still_foreign' | 'system_pkg_blocklist' | 'guard_disabled' | 'probe_failed'
      }
    """
```

### Границы (контракт)

- Зависит только от proxy-методов публикатора: `self.adb`, `self.dump_ui`, `self.tap_element`, `self.log_event`, `self.platform_cfg['package']` (per memory `feedback_publisher_proxy_api`).
- Не изменяет глобального состояния публикатора (не пишет в `self.step`, не трогает `self._record_event`).
- Idempotent: безопасно вызвать дважды подряд.
- Никогда не raise'ит — все exception'ы внутри ловятся (страховка от того, чтобы guard сам не стал источником регрессии).

### Allowlist (НЕ считается foreign)

```python
YT_FOREGROUND_ALLOWLIST = frozenset({
    'com.google.android.youtube',
    'com.google.android.youtube.tv',
    'com.android.permissioncontroller',
    'com.google.android.permissioncontroller',
    'com.samsung.android.permissioncontroller',
})
```

Permission-controller'ы в allowlist потому, что у нас уже есть permission-tap loop в `_normalize_yt_state_pre_upload`, который сам обрабатывает диалоги разрешений. Foreign-guard не должен force-stop'ить permissioncontroller (это сломает grant-flow).

### System-package block-list (нельзя force-stop'ить даже если foreground)

```python
FOREIGN_FORCE_STOP_BLOCKLIST = frozenset({
    'android',
    'com.android.systemui',
    'com.android.settings',
    'com.google.android.gms',
    'com.google.android.packageinstaller',
})
```

Если topResumed в blocklist — escalation останавливается на BACK (без force-stop), возвращаем `unrecoverable_reason='system_pkg_blocklist'`. Это страховка от случая, где Android system dialog перехватил foreground.

### Skip-keys (для шага escalation (a))

```python
FOREIGN_FOREGROUND_SKIP_KEYS = [
    'Закрыть', 'Отмена', 'Cancel', 'Не сейчас', 'Не сегодня',
    'Позже', 'Later', 'Skip', 'Пропустить', 'Не входить',
    'Нет, спасибо', 'No thanks',
]
```

### Kill-switch

```python
import os
GUARD_DISABLED = os.environ.get('YT_FOREIGN_FOREGROUND_GUARD_DISABLE') == '1'
```

Если `True`, guard работает в режиме `allow_recovery=False` (detect+log only).

---

## 3. Внутренний flow `_dismiss_foreign_foreground` пошагово

```
ВХОД (source, allow_recovery)
  │
  ▼
1. probe topResumedActivity
   adb('dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity', timeout=5)
   parse pkg/activity (regex по существующему паттерну Task C)
   │
   ├── parse fail / empty → return {foreign_detected:False,
   │                                unrecoverable_reason:'probe_failed', ...}
   │     log_event 'info', category='yt_foreign_foreground_probe_failed'
   │
   ▼
2. allowlist check: top_pkg in YT_FOREGROUND_ALLOWLIST?
   │
   ├── YES → return {foreign_detected:False, top_package:pkg, ...}
   │         (нет лога — нормальный путь, не шумим)
   │
   ▼
3. FOREIGN DETECTED
   log_event 'info', category='yt_foreign_foreground_detected',
     meta={source, top_package, top_activity}
   │
   ▼
4. kill-switch / dry-run gate
   if GUARD_DISABLED or not allow_recovery:
       log_event info, category='yt_foreign_foreground_guard_disabled'
       return {foreign_detected:True, recovered:False,
               unrecoverable_reason:'guard_disabled', escalation_steps:[]}
   │
   ▼
5. ESCALATION (a) — skip-tap
   ui = self.dump_ui()
   tapped = self.tap_element(ui, FOREIGN_FOREGROUND_SKIP_KEYS, clickable_only=True)
   if tapped:
       time.sleep(2)
       escalation_steps.append('skip_tap')
       re-probe → если в allowlist → SUCCESS
   │
   ▼
6. ESCALATION (b) — BACK ×2
   for i in (1, 2):
       self.adb('input keyevent KEYCODE_BACK')
       time.sleep(1)
       re-probe → если в allowlist → SUCCESS
         (escalation_steps.append(f'back_x{i}'))
   │
   ▼
7. ESCALATION (c) — force-stop foreign + relaunch YT
   if top_pkg in FOREIGN_FORCE_STOP_BLOCKLIST:
       log_event 'error', category='yt_foreign_foreground_unrecoverable_blocklist',
         meta={top_package, top_activity}
       return {recovered:False, unrecoverable_reason:'system_pkg_blocklist',
               escalation_steps:['skip_tap','back_x1','back_x2']}
   else:
       self.adb(f'am force-stop {top_pkg}')
       time.sleep(1.5)
       self.adb(f'am start -p {yt_pkg} -a android.intent.action.MAIN '
                f'-c android.intent.category.LAUNCHER')
       time.sleep(3)
       escalation_steps.append('force_stop_and_relaunch')
       final-probe topResumedActivity
   │
   ▼
8. RESULT
   if final top_pkg in allowlist:
       log_event 'info', category='yt_foreign_foreground_recovered', ...
       return {recovered:True, ...}
   else:
       log_event 'error', category='yt_foreign_foreground_unrecoverable',
         meta={..., final_top_package:<after escalation>}
       return {recovered:False, unrecoverable_reason:'still_foreign', ...}
```

### Ключевые нюансы

- **Re-probe после каждой эскалации.** Может оказаться, что после BACK×1 уже всё ок — не лупим следующий шаг зря.
- **Тайминги** скопированы с существующего `_normalize_yt_state_pre_upload`: sleep 1.5 после force-stop, 3 после LAUNCHER, 2 после tap, 1 после BACK.
- **timeout=5 на dumpsys** — короткий, потому что dumpsys стабильно отвечает <1с.
- **Нет рекурсии** в самом `_dismiss_foreign_foreground` — если recovery «не удержался» (Samsung вернулся через 100мс), это поймает следующий checkpoint.
- **`mCurrentFocus` НЕ используется** для решения — он часто врёт на мульти-окнах (PiP, drawer). Решающий сигнал = `topResumedActivity`.

---

## 4. Интеграция в два checkpoint'а

### Checkpoint #1 — `_normalize_yt_state_pre_upload` (publisher_youtube.py:764-810)

Один вызов в самом конце, ПОСЛЕ существующего `log_event 'yt_pre_upload_state_normalized'`:

```python
def _normalize_yt_state_pre_upload(self) -> None:
    # ... существующий код без изменений ...
    self.log_event(
        'info', 'yt_pre_upload_state_normalized',
        meta={'category': 'yt_pre_upload_state_normalized',
              'package': yt_pkg, 'force_stop_done': True},
    )
    # WP #74 Round 2 (2026-05-18): foreign-foreground guard.
    # Если после force-stop+LAUNCHER чужой пакет перехватил foreground —
    # пытаемся вежливо дисмиссить. Non-blocking: если recovery failed,
    # _select_gallery_video downstream поймает и сделает fail-fast.
    self._dismiss_foreign_foreground(source='post_normalize')
```

### Checkpoint #2 — `_select_gallery_video` (publisher_youtube.py:617-761)

Добавляем `_foreign_retry_left: int = 1` параметр (одно-уровневая рекурсия), вставляем guard ПЕРЕД fail-fast emit'ом:

```python
def _select_gallery_video(
    self, remote_media_path: str,
    *, _foreign_retry_left: int = 1,
) -> bool:
    """... (existing docstring, без изменений) ..."""
    # ... существующий parse loop без изменений ...

    if not video_selected:
        log.error('YouTube: видео не найдено в gallery picker — abort')

        # WP #74 Round 2: foreign-foreground guard перед fail-fast emit'ом.
        guard_result = self._dismiss_foreign_foreground(
            source='pre_gallery_select_fail_fast',
        )
        if guard_result['recovered'] and _foreign_retry_left > 0:
            log.info('  Gallery probe retry после foreign-foreground recovery')
            self.log_event(
                'info', 'yt_gallery_retry_after_foreign_recovery',
                meta={'category': 'yt_gallery_retry_after_foreign_recovery',
                      'foreign_top_package': guard_result['top_package'],
                      'escalation_steps': guard_result['escalation_steps']},
            )
            return self._select_gallery_video(
                remote_media_path, _foreign_retry_left=0,
            )

        try:
            self._save_debug_artifacts('yt_gallery_no_video')
        except Exception:
            pass
        diag = [{'cx': it[4], 'cy': it[5], 'desc': (it[6] or '')[:120]}
                for it in (last_all_items or [])[:10]]

        # Существующие top_act/cur_pkg probe'ы оставляем для back-compat
        # (SQL дашбордов читает эти строки в исходном формате).
        top_act = ''
        try:
            _act_raw = self.adb(
                'dumpsys activity activities 2>/dev/null '
                '| grep -m1 "topResumedActivity"', timeout=5
            ) or ''
            top_act = _act_raw.strip()[:200]
        except Exception:
            pass
        cur_pkg = ''
        try:
            _pkg_raw = self.adb(
                'dumpsys window 2>/dev/null | grep -m1 "mCurrentFocus"',
                timeout=5,
            ) or ''
            cur_pkg = _pkg_raw.strip()[:200]
        except Exception:
            pass

        meta = {
            'category': 'yt_gallery_no_video_candidate',
            'platform': self.platform,
            'step': 'yt_gallery_select',
            'all_clickable_count': len(last_all_items or []),
            'first_clickables': diag,
            'top_resumed_activity': top_act,
            'current_package': cur_pkg,
        }
        if guard_result['foreign_detected']:
            meta.update({
                'foreign_foreground_detected': True,
                'foreign_foreground_top_package': guard_result['top_package'],
                'foreign_foreground_top_activity': guard_result['top_activity'],
                'foreign_foreground_recovered': guard_result['recovered'],
                'foreign_foreground_unrecoverable_reason':
                    guard_result['unrecoverable_reason'],
                'foreign_foreground_escalation_steps':
                    guard_result['escalation_steps'],
            })
            if _foreign_retry_left == 0:
                meta['foreign_foreground_retry_exhausted'] = True
        self.log_event(
            'error', 'YT: видео не найдено в gallery picker — fail-fast',
            meta=meta,
        )
        return False
    return True
```

### Нюансы интеграции

- `_foreign_retry_left` с underscore — приватный параметр, не для внешних caller'ов. Default `1` сохраняет внешнее API.
- Рекурсия ограничена одним уровнем — на втором заходе `_foreign_retry_left=0`, retry не сработает даже если guard опять найдёт чужой foreground.
- Если guard на втором заходе вернул `foreign_detected=True` — в meta поедет `foreign_foreground_retry_exhausted=True` (для триажа: «recovery не удержался»).
- Существующие `top_act` / `cur_pkg` probe'ы НЕ удаляем — back-compat с дашбордами/SQL, которые читают полные строки. Overhead extra adb-вызова приемлем (~50ms, fail-fast путь редкий).
- Caller (`publish_youtube_short` line 1503) НЕ меняем — внешняя сигнатура `_select_gallery_video(media_path)` сохранена.

---

## 5. Observability, error handling, kill-switch

### Новые event-категории (в `meta.category`)

| Категория | Когда | Уровень |
|---|---|---|
| `yt_foreign_foreground_detected` | Top-pkg НЕ в allowlist, перед escalation | `info` |
| `yt_foreign_foreground_recovered` | После escalation top-pkg вернулся в allowlist | `info` |
| `yt_foreign_foreground_unrecoverable` | Escalation отработал, top-pkg всё ещё чужой | `error` |
| `yt_foreign_foreground_unrecoverable_blocklist` | Чужой top-pkg в `FOREIGN_FORCE_STOP_BLOCKLIST` — escalation остановлен на BACK | `error` |
| `yt_foreign_foreground_guard_disabled` | Env-flag или `allow_recovery=False` | `info` |
| `yt_foreign_foreground_probe_failed` | dumpsys timeout / parse fail | `info` |
| `yt_gallery_retry_after_foreign_recovery` | В `_select_gallery_video` запускаем второй проход | `info` |

Зонтичный `yt_gallery_no_video_candidate` сохраняется как top-level `error_code` (заявка на дашборды) — новые поля идут как ДОПОЛНЕНИЕ к существующему meta.

### Meta-словарь recovered/unrecoverable событий

```json
{
  "category": "yt_foreign_foreground_recovered",
  "platform": "YouTube",
  "source": "post_normalize",
  "top_package": "com.sec.android.app.samsungapps",
  "top_activity": "ForceLoginSamungAccountActivity",
  "escalation_steps": ["skip_tap", "back_x1", "force_stop_and_relaunch"],
  "final_top_package": "com.google.android.youtube",
  "unrecoverable_reason": null
}
```

### Триаж SQL (пример)

```sql
SELECT
  e->'meta'->>'category' AS cat,
  e->'meta'->>'top_package' AS top_pkg,
  COUNT(*) AS hits
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events) e
WHERE pt.platform = 'YouTube'
  AND pt.started_at > '2026-05-18'
  AND (e->'meta'->>'category') LIKE 'yt_foreign_foreground_%'
GROUP BY 1, 2
ORDER BY hits DESC;
```

### Error handling

- `_dismiss_foreign_foreground` НЕ raise'ит. Все exception'ы внутри (adb timeout, dump_ui exception) ловятся → возврат с `unrecoverable_reason='probe_failed'` или `'still_foreign'`, лог-event `info`.
- `dump_ui` / `tap_element` уже robust в `DevicePublisher`. Если skip-tap провалится (тег не найден / dump пустой) — переходим на BACK, не падаем.
- `am force-stop` для несуществующего пакета возвращает rc=0 (Android quirk), безвреден.

### Kill-switch

- `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` → `allow_recovery=False`. Guard всё ещё detect'ит чужой foreground и эмитит `yt_foreign_foreground_detected` + `yt_foreign_foreground_guard_disabled` события, но НЕ делает BACK / force-stop / relaunch.
- Включить на prod: `export YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` в ecosystem config + `pm2 restart 34 autowarm --update-env`. Совпадает с паттерном WP #82.
- Документация: добавить флаг в `PUBLISH-NOTES.md` раздел «Feature flags».

### Что НЕ меняется

- `publish_tasks.error_code` — остаётся `yt_gallery_no_video_candidate` (первое error-event в pipeline, per memory `feedback_publisher_error_code_misleading`).
- Дашборды — все существующие фильтры по `error_code='yt_gallery_no_video_candidate'` работают. Новые ветки видны через `meta->foreign_foreground_detected`.
- `_save_debug_artifacts('yt_gallery_no_video')` — сохраняем (UI dump перед fail-fast, нужен для post-mortem).

### Acceptance signal (24h verify)

После деплоя на prod:

1. Любой `yt_gallery_no_video_candidate` с `meta.foreign_foreground_recovered=true` → success path сработал хотя бы раз → guard живой.
2. Любой `yt_gallery_no_video_candidate` БЕЗ `meta.foreign_foreground_detected` → старый класс фейлов (gallery просто не открылась) — НЕ регрессия от guard'а.
3. Если в 24h окне 0 фейлов с `meta.foreign_foreground_*` — триггер редкий (1 на 3 дня в исходных данных). Нужно ждать дольше; либо guard прячет рецидивы через recovery (good).

---

## 6. Testing strategy

### Stub-инфра

Переиспользуем `_StubPub(YouTubeMixin)` из `test_publisher_youtube_state_normalize.py` (line 19-37). Расширяем `_save_debug_artifacts = MagicMock()` для checkpoint #2.

### Risk: mock-drift (memory `feedback_mock_proxy_drift`)

Codex review не ловит cross-class-boundary факты. Контр-мера:

1. Live smoke на testbench перед merge (обязательно).
2. Перед PR — `pytest tests/test_publisher_youtube_*.py -v` на autowarm-testbench, не только в isolated worktree.

### Unit-тесты `_dismiss_foreign_foreground`

`TestDismissForeignForeground` — 11 кейсов:

| # | Scenario | Expected |
|---|---|---|
| 1 | YT уже foreground | `foreign_detected:False` |
| 2 | permissioncontroller в allowlist | `foreign_detected:False` (НЕ escalation) |
| 3 | Samsung Account → skip-tap success | `recovered:True, escalation_steps:['skip_tap']` |
| 4 | Samsung Account → BACK×1 success | `recovered:True, escalation_steps:['back_x1']` |
| 5 | Samsung Account → BACK×2 success | `recovered:True, escalation_steps:['back_x1','back_x2']` |
| 6 | Samsung Account → force-stop+relaunch success | `recovered:True`, `adb` called with `am force-stop com.sec.android.app.samsungapps` |
| 7 | system pkg (`android`) blocklist | `recovered:False, unrecoverable_reason:'system_pkg_blocklist'`, НЕТ `am force-stop android` в adb calls |
| 8 | foreign после всей escalation не сдвинулся | `recovered:False, unrecoverable_reason:'still_foreign'` |
| 9 | kill-switch ENV `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` | `recovered:False, unrecoverable_reason:'guard_disabled'`, НЕТ BACK/force-stop в adb calls |
| 10 | `allow_recovery=False` | как #9 |
| 11 | probe failure (dumpsys пустой) | `foreign_detected:False, unrecoverable_reason:'probe_failed'` |

Два теста парсера:

- `test_parse_top_resumed_extracts_pkg_and_activity` — `topResumedActivity=ActivityRecord{... com.foo/.bar.Activity ...}` → `('com.foo', 'bar.Activity')`.
- `test_parse_top_resumed_handles_malformed` → `(None, None)`.

### Интеграционные тесты

**`test_publisher_youtube_state_normalize.py` — добавить 1 тест:**

```python
def test_normalize_calls_foreign_foreground_guard():
    pub = _StubPub()
    pub._dismiss_foreign_foreground = MagicMock(return_value={
        'foreign_detected': False, 'top_package': None, 'top_activity': None,
        'recovered': False, 'escalation_steps': [], 'unrecoverable_reason': None,
    })
    pub._normalize_yt_state_pre_upload()
    pub._dismiss_foreign_foreground.assert_called_once_with(source='post_normalize')
```

**`test_publisher_youtube_picker.py` — добавить 3 теста:**

1. `test_select_gallery_video_calls_guard_before_fail_fast` — если parse-loop не нашёл видео, `_dismiss_foreign_foreground(source='pre_gallery_select_fail_fast')` вызван хотя бы раз.
2. `test_select_gallery_video_retries_once_after_recovery` — guard возвращает `recovered:True` первый раз, `recovered:False` второй → `_select_gallery_video` вернул `False`, parse-loop отработал ДВА раза, event `yt_gallery_retry_after_foreign_recovery` залогирован, `foreign_foreground_retry_exhausted=True` в fail-fast meta.
3. `test_select_gallery_video_no_retry_when_unrecovered` — guard сразу `recovered:False` → parse-loop ОДИН раз, fail-fast meta содержит `foreign_foreground_unrecoverable_reason`.

### Live smoke (обязательно перед merge)

На autowarm-testbench (phone из memory `reference_testbench_smoke_paths`):

1. **Baseline** — `pytest tests/test_publisher_youtube_*.py -v` на тестбенче.
2. **Synthetic foreign foreground** — `adb shell am start -n com.sec.android.app.samsungapps/.initialization.ForceLoginSamungAccountActivity` (если устройство держит этот dialog). Триггерим publish_youtube_short на testbench, смотрим в DB events: должен появиться `yt_foreign_foreground_detected` + либо `..._recovered`, либо `..._unrecoverable`. Если ForceLogin недоступен — fallback на mock-foreign (`am start com.android.calculator2/.Calculator`).
3. **Happy path не сломан** — обычный testbench-smoke publish_youtube_short с чистым YT-состоянием: должен пройти без `yt_foreign_foreground_detected` (или с `foreign_detected:False`).

Acceptance перед PR-merge: оба сценария зелёные + 14/14 unit-тестов + `pytest tests/` целиком зелёный (нет collateral регрессий).

### Codex review

После self-review — `git diff main..HEAD | codex review -` раундами до 0 P1 (memory `feedback_codex_review_specs`, через stdin per `feedback_codex_sandbox_broken`).

---

## 7. Файлы, которые меняются

| Файл | Тип изменения | Прибл. строк |
|---|---|---|
| `publisher_youtube.py` | +1 метод `_dismiss_foreign_foreground` (~80 строк) + 1 вызов в `_normalize_yt_state_pre_upload` + ~30 строк интеграции в `_select_gallery_video` | ~115 |
| `tests/test_publisher_youtube_foreign_foreground.py` | новый файл, ~13 тестов | ~250 |
| `tests/test_publisher_youtube_state_normalize.py` | +1 тест | ~15 |
| `tests/test_publisher_youtube_picker.py` | +3 теста | ~80 |
| `PUBLISH-NOTES.md` | +раздел про `YT_FOREIGN_FOREGROUND_GUARD_DISABLE` env-flag | ~10 |

Итого: ~470 строк диффа (включая тесты), 5 файлов.

---

## 8. Деплой / rollback

**Деплой:** PR в `GenGo2/delivery-contenthunter`, после merge auto-push hook на prod autowarm (memory `reference_autowarm_git_hook`). `pm2 restart 34 autowarm`. Live smoke на одной prod-задаче — должна пройти без guard-событий (happy path).

**Rollback (если guard сам начал регрессировать):**

- Immediate: `export YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` в ecosystem config + `pm2 restart 34 autowarm --update-env` (kill-switch, без коммита).
- Permanent: revert merge commit.

**24h post-deploy verify:** SQL из секции 5 + следующий триаж WP-by-WP (паттерн `2026-05-18-wp-triage-testing-status.md`).
