# TT Music-Rights Coverage + Post-Accept Success Detection — Design

**Дата:** 2026-05-11
**Автор:** Claude (Opus 4.7 1M)
**Триггер:** Регрессия после ship'а music-rights handler (PR #28, commit `8ec5c53`, merged 2026-05-10). Метрика: **0 успешных публикаций TT с music-rights диалогом за 72 часа**; `tt_upload_confirmation_timeout` = 7 fails / 24h.
**Связанные документы:**
- `docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md` (PR #28 spec)
- Memory: `project_tt_music_rights_dialog_shipped`, `reference_tt_activities_observed`, `feedback_publisher_error_code_misleading`

---

## Проблема

После ship'а music-rights handler (PR #28) production-метрика по TT-публикациям регрессировала. Из 5 свежайших failed task'ов за 24 часа выявлены два независимых root cause:

### RC-A — Handler не срабатывает (≈40% timeout'ов: tasks 4536, 4488, 4482)

Music-rights диалог появляется на экране (AI Unstuck визуально его видит и вручную пытается тапнуть `music rights`), но `_detect_tt_music_rights_dialog` возвращает `False`. Причины:
- Strict matcher требует **EXACT** match по title-node против 4 заранее зафиксированных вариантов (`'Подтвердить и опубликовать видео?'` / `'Confirm and publish video'` ± `?`).
- TT минорно обновил UI: либо новый текст title-node, либо изменилась XML-структура (title-text оказался в desc или в sub-node), и EXACT не matches.
- UI dump'ы для failed tasks **не сохраняются** в текущем коде на этой ветке — точное содержимое нового XML неизвестно.

### RC-B — Handler сработал, но post-accept screen не появляется (≈60%: tasks 4542, 4541, 4540, 4539)

Event `tt_music_rights_accepted` с `button_tapped=true` залогирован успешно. Через ~30-50 сек AI Unstuck триггерит «An unexpected screen is blocking upload confirmation». UPLOAD_OK substring markers (`Загружается`, `Для вас`, `DetailActivity`, `Опубликовано` и т.д.) не matches в течение 3-минутного timeout-loop'а. Причины (гипотезы):
- TT после accept'а остаётся в composer (`SAASceneWrapperActivity` — наблюдалось 2026-05-11, memory `reference_tt_activities_observed`), но в новом state'е, где UPLOAD_OK substring markers не появляются.
- Возможно появляется промежуточный экран обработки/проверки, отсутствующий в UPLOAD_OK списке.
- AI Unstuck видит экран как «unexpected», но dismissed-операции не возвращают TT в success-state.

Без сохранённого XML мы не можем гарантированно классифицировать RC-B. Это критично — отсюда требование инструментации.

### Метрика успеха

(Codex round 1, P2#8: rate-based, не traffic-зависимая абсолюта.)

- **0** task'ов имеющих `tt_music_rights_accepted=true` И `tt_upload_confirmation_timeout` И **без** промежуточного `tt_upload_confirmed_*` event'а в течение 24h после rollout (Codex round 2, P2#3 — narrow gate, не задеваемый unrelated confirmation-loop timeouts).
- При наличии ≥10 events `tt_music_rights_accepted=true` за 24h: доля задач завершившихся `tt_upload_confirmed_*` (любым из путей: early, post_music_rights activity, штатный UPLOAD_OK substring) ≥ **80%**.
- 0 events `tt_upload_confirmed_post_music_rights` followed by downstream `publish_failed_*` (false-positive rate должен быть 0 для этого детектора; non-zero = регрессия дизайна → тянуть streak threshold выше или добавлять signals).
- При появлении **любого** `tt_music_rights_button_changed_suspect` event'а — сохранённый XML должен быть прочитан и константы расширены в следующей итерации.

---

## Скоп

**В скопе:**
- Изменения в `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`.
- Расширение тестов в `tests/test_publisher_tt_music_rights.py`.
- Два feature flag'а для постепенной активации.

**Не в скопе:**
- Изменения strict `_detect_tt_music_rights_dialog` (остаётся primary).
- Изменения `_strict_tap_clickable`, `_tick_tt_music_rights_checkbox` (рабочие).
- Изменения `_TT_MUSIC_RIGHTS_TITLE_MARKERS`/`_BUTTON`/`_CHECKBOX` константы (расширение constants — отдельная задача после анализа собранных XML dump'ов).
- AI Unstuck изменения (separate concern; downstream improvement).
- `tt_fg_lost` (отдельный backlog, наблюдается на task 4523).

---

## Архитектура

Один файл — `publisher_tiktok.py`. Изменения за двумя feature-flag'ами:

| Flag | Default | Покрытие |
|---|---|---|
| `TT_MUSIC_RIGHTS_FALLBACK_ENABLED` | `false` | RC-A: fallback matcher + dump XML на fallback-match |
| `TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED` | `false` | RC-B: activity-based success-check после accept |
| `TT_DUMP_POST_MUSIC_RIGHTS_XML` | `false` | RC-B: per-iteration XML dump после accept (инструментация, opt-in) |

При **всех** flag=false поведение идентично текущему prod (PR #28) — никаких записей в `/tmp`, никаких новых code-path'ов. Активация — одной env-var, выключение симметрично. (Codex round 1, P1#1: dump-flag не должен быть on-by-default, чтобы не писать UI-XML в prod без явного opt-in.)

### Точки изменений

| # | Где | Что |
|---|---|---|
| **RC-A.1** | `_detect_tt_music_rights_dialog` (стр. 209-257) | Новый метод `_detect_tt_music_rights_dialog_fallback(ui_xml) -> bool` |
| **RC-A.1b** | Same area | Новый метод `_detect_tt_music_rights_dialog_evidence_only(ui_xml) -> bool` — evidence-only path, без auto-handle |
| **RC-A.2** | `_handle_tt_music_rights_dialog` (стр. 347-389) | Hybrid invoke: сначала strict, если False и flag enabled — fallback. На fallback-match: сохранить полный XML + log_event с `matched_via='fallback'`. Evidence-only path → dump + log без handle |
| **RC-B.1** | `publish_tiktok` (стр. 391+) | Сброс `_music_rights_just_accepted_iter = None`, `_music_rights_accepted_ts = None`, `_post_mr_good_streak = 0` в начале (рядом с `_music_rights_iter = 0`) |
| **RC-B.2** | Upload-confirmation loop, в ветке музыкальных-прав `if handled: time.sleep(2); continue;` (стр. 922-924, где `handled = self._handle_tt_music_rights_dialog(ui)` — Codex round 1, P2#6: явно фиксируем что это music-rights branch, не любой обработанный dialog) | Set `_music_rights_just_accepted_iter = wait` и `_music_rights_accepted_ts = time.time()`. **Также:** reset `_music_rights_iter = 0` (Codex round 1, P1#3: декаплинг counter'а от post-accept фазы — после успешного handle dialog не должен накапливать budget на отдельную фазу) |
| **RC-B.3** | Тот же loop, после `tiktok_active` блока (~стр. 798+), но до UPLOAD_OK substring check | Активный activity-based success-check с 2-iter good-streak guard (см. ниже) |
| **RC-B.4** | Тот же loop | Per-iteration XML dump после accept (логарифмическая частота, opt-in) |

Не трогаем: AI Unstuck, MAX_* константы, существующие markers (EXACT), audio-dialog handler, music_rights_stuck cap (но reset counter после handled — см. RC-B.2).

---

## Детальный дизайн

### RC-A.1: Fallback matcher

```python
def _detect_tt_music_rights_dialog_fallback(self, ui_xml: str) -> bool:
    """Looser match для случаев когда TT обновил title-текст.

    Срабатывает ТОЛЬКО когда strict _detect_tt_music_rights_dialog вернул
    False. Условия match (ВСЕ должны быть true):

    1. Substring pre-filter (case-INSENSITIVE): low_xml = ui_xml.lower();
       в low_xml есть одна из _TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS
       (все substring'и заранее lowercase).
    2. Структурная проверка через XML parse — ВСЕ три должны быть true
       (Codex round 2, P1#1: предыдущая 'OR generic_checkbox' могла
       fall-positive на обычном composer'е где «music rights» появляется
       в hyperlink/help-tip + есть generic checkbox + есть Publish-кнопка):
       a) has_checkbox_label_exact: node с text/desc EXACT in
          _TT_MUSIC_RIGHTS_CHECKBOX (наш известный checkbox-label).
       b) has_clickable_button_exact: clickable=true node с text/desc
          EXACT in _TT_MUSIC_RIGHTS_BUTTON.
       c) (a) и (b) находятся **в общем dialog-контейнере**: их bounds
          пересекаются по Y-диапазону (центр одного попадает в bounds
          другого ±200px) — структурный признак single-dialog.

    Если кто-то из (a)/(b)/(c) фейлит → fallback возвращает False.
    Кейс «substring есть, но это не диалог» (composer caption-link или
    help screen) — НЕ ловится fallback'ом, перенаправляется в evidence-only
    path где dump'ится без auto-handle.
    """
```

Константа (все substring'и в lowercase, поскольку сравниваем с `.lower()` копией):
```python
_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS = [
    'права на использование музыки',
    'music usage rights',
    'music rights',
    'rights confirmation',
    'подтверждение прав',
]
```

Возвращает `True` ⟺ lowercase substring найден AND (specific structure OR generic checkbox) AND button accept присутствует. Иначе `False`.

### RC-A.1b: Evidence-only fallback (без auto-handle)

Для случая когда TT поменял **и** title **и** button-текст (Codex round 1, P2#5: «button EXACT» — точка хрупкости). Дополнительный, более слабый detector:

```python
def _detect_tt_music_rights_dialog_evidence_only(self, ui_xml: str) -> bool:
    """Slack-match только для логирования + dump.

    Условия:
      1. Substring 'music rights' / 'права … музыки' в lowercase ui_xml.
      2. has_generic_checkbox в дереве.
      3. EXACT-button accept НЕ найден.

    НЕ возвращает True для auto-accept. Caller использует этот сигнал
    только чтобы dump XML и залогировать suspect-event — фикс будет
    после ручного review dump'а.
    """
```

В `_handle_tt_music_rights_dialog`:
- Если strict-fallback оба False, но `_detect_tt_music_rights_dialog_evidence_only` True → `log_event('warning', ..., meta={'category': 'tt_music_rights_button_changed_suspect', ...})` + dump XML. Возвращает `False` (не handle'им — даём fall-through существующей логике).

Это не «спасает» текущую публикацию, но гарантирует что **следующая итерация дизайна** будет с реальными данными о новом button-тексте.

### RC-A.2: Hybrid invocation в `_handle_tt_music_rights_dialog`

```python
def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
    matched_via = None
    fallback_enabled = (os.environ.get('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'false')
                        .lower() == 'true')
    if self._detect_tt_music_rights_dialog(ui_xml):
        matched_via = 'strict'
    elif fallback_enabled and self._detect_tt_music_rights_dialog_fallback(ui_xml):
        matched_via = 'fallback'
        dump_path = self._save_dump_for_fallback_review(ui_xml, suffix='fallback')
        self.log_event(
            'info',
            'TikTok: music rights dialog matched via fallback',
            meta={'category': 'tt_music_rights_fallback_match',
                  'dump_path': dump_path,
                  'platform': self.platform})
    else:
        # Evidence-only path: substring + generic checkbox найдены, но
        # button EXACT не нашли. Не handle'им — только dump + log.
        if (fallback_enabled
            and self._detect_tt_music_rights_dialog_evidence_only(ui_xml)):
            dump_path = self._save_dump_for_fallback_review(
                ui_xml, suffix='button_changed_suspect')
            self.log_event(
                'warning',
                'TikTok: music rights-like dialog suspect, button EXACT not found',
                meta={'category': 'tt_music_rights_button_changed_suspect',
                      'dump_path': dump_path,
                      'platform': self.platform})
        return False

    # ... existing tick + tap flow ...
    # log_event meta получает 'matched_via': matched_via
```

`_save_dump_for_fallback_review(ui_xml, suffix)`:
- Создаёт директорию `/tmp/autowarm_ui_dumps/` через `os.makedirs(..., exist_ok=True)` (Codex round 1, P2#7).
- Имя файла: `tt_music_rights_{suffix}_{task_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.xml` — миллисекундный timestamp + короткий random suffix защищают от коллизии при retries в тот же sec (Codex round 1, P3#9; Codex round 2, P3#1).
- Best-effort write. На exception — `log.warning(...)` и возврат `'write_failed'`. Никогда не raise'ит.

### RC-B.3: Activity-based success-check (внутри upload-confirmation loop)

Срабатывает ТОЛЬКО при условиях: `_music_rights_just_accepted_iter is not None`, `tiktok_active=True`, прошло ≥ 3 итерации после accept (>=9 сек), И зафиксировано **3 подряд good observation'а** (Codex round 1, P1#2 + Codex round 2, P1#2: одиночное/двойное navigate-away всё ещё может быть транзитом или queued/cancelled state'ом; 3 iters × 3 sec = 9 сек stable — обоснованный безопасный порог).

State, добавляемый в publisher:
```python
self._post_mr_good_streak = 0  # счётчик consecutive «good» observations
```

Сбрасывается рядом с `_music_rights_just_accepted_iter = None` в начале `publish_tiktok`.

```python
# Вставка после блока `tiktok_active` проверки (~стр. 798), до UPLOAD_OK substring check.
if (os.environ.get('TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED', 'false').lower() == 'true'
    and self._music_rights_just_accepted_iter is not None
    and tiktok_active):

    iters_since = wait - self._music_rights_just_accepted_iter
    if iters_since >= 3:  # минимум 9 сек на transition (Codex round 2, P1#2)
        # Анти-сигнал #1: композер ещё на стеке = не успех
        composer_on_stack = (
            'SAASceneWrapperActivity' in act
            or 'reels_editor' in ui
            or 'clips_creation' in ui
            or any(m in ui for m in STILL_ON_EDITOR)
        )
        # Анти-сигнал #2: failure-toast или повторный music-rights диалог
        # (= TT отверг публикацию).
        post_publish_failure_hint = (
            self._detect_tt_music_rights_dialog(ui)
            or (os.environ.get('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'false').lower() == 'true'
                and self._detect_tt_music_rights_dialog_fallback(ui))
            or any(m in ui for m in (
                'Не удалось опубликовать', 'Failed to publish',
                'Не удалось загрузить', 'Upload failed',
                'Попробуйте ещё раз', 'Try again',
            ))
        )
        # Анти-сигнал #3: upload в процессе (queued state может маскироваться
        # под success — Codex round 2, P1#2). Если есть явная индикация upload
        # in progress — это НЕ success, а ожидание.
        upload_in_progress_hint = any(m in ui for m in (
            'Загружается', 'Uploading',
            'Загружается видео', 'Video uploading',
            'Обрабатывается', 'Processing',
        ))
        post_publish_activity = any(a in act for a in (
            'MainActivity',          # домашний экран TT (Для вас / Подписки)
            'DetailActivity',        # страница опубликованного видео
            'ProfileActivity',       # вкладка профиля
            'UserProfileActivity',
        ))
        is_good_iter = (post_publish_activity
                        and not composer_on_stack
                        and not post_publish_failure_hint
                        and not upload_in_progress_hint)

        if is_good_iter:
            self._post_mr_good_streak += 1
        else:
            self._post_mr_good_streak = 0  # reset на любом плохом сигнале

        if self._post_mr_good_streak >= 3:  # 3 подряд = ~9 сек стабильно
            log.info(f'  ✅ TikTok: post-music-rights navigate-away stable '
                     f'({self._post_mr_good_streak} iters) — публикация подтверждена')
            self.log_event('info',
                'TikTok: публикация подтверждена (post-music-rights activity)',
                meta={'category': 'tt_upload_confirmed_post_music_rights',
                      'topActivity': act.strip()[:120],
                      'iters_after_accept': iters_since,
                      'good_streak': self._post_mr_good_streak})
            upload_confirmed = True
            break
```

**Почему это работает:**
- memory `reference_tt_activities_observed`: `SAASceneWrapperActivity` — composer/wrapper; уход = navigate-away.
- **3 подряд good iters** (~9 сек) защищает от транзитного MainActivity (Codex round 2, P1#2: queued/cancelled может транзитно показать MainActivity).
- **post_publish_failure_hint** — failure-toast'ы И повторное появление music-rights диалога.
- **upload_in_progress_hint** — queued state guard (Codex round 2, P1#2).
- `iters_since >= 3` — даём TT минимум 9 сек на transition.

**Marker brittleness (известное ограничение):** activity-имена (`MainActivity`, `DetailActivity`, etc.) и failure-toast строки — зависят от version'а TT и языка приложения. Это сознательная trade-off ради быстрого ship'а; точные строки будем калибровать после первых dump'ов из prod'а (Codex round 1, P3#10).

### RC-B.4: Per-iteration XML dump

```python
if (os.environ.get('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'false').lower() == 'true'
    and self._music_rights_just_accepted_iter is not None):

    iters_since = wait - self._music_rights_just_accepted_iter
    if iters_since in (1, 3, 5, 10, 20, 40):  # логарифмическая частота
        try:
            os.makedirs('/tmp/autowarm_ui_dumps', exist_ok=True)  # Codex round 1, P2#7
            # ms-timestamp + uuid suffix — защита от коллизии при retries
            # в той же секунде (Codex round 1, P3#9; Codex round 2, P3#1)
            path = (f'/tmp/autowarm_ui_dumps/'
                    f'tt_post_music_rights_{self.task_id}'
                    f'_iter{iters_since}_{int(time.time() * 1000)}'
                    f'_{uuid.uuid4().hex[:8]}.xml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ui or '')
            log.info(f'  💾 post-music-rights dump (iter+{iters_since}): {path}')
        except Exception as e:
            log.warning(f'  ⚠️ Не удалось сохранить post-music-rights dump: {e}')
```

Default `false` (Codex round 1, P1#1) — opt-in активация в rollout step 2. Цель — собрать XML evidence для следующей итерации (если RC-B не покрывается activity-check'ом).

---

## Error handling

| Сценарий | Поведение |
|---|---|
| `_detect_tt_music_rights_dialog_fallback` XML parse fails | Возврат `False` (как в strict). |
| `_save_dump_for_fallback_review` write fails | log warning, продолжаем. Поле `dump_path='write_failed'` в event meta. |
| Per-iteration dump write fails | log warning, продолжаем. |
| `dumpsys activity` timeout / empty `act` | `tiktok_active` уже handle'ит; post-music-rights success-check просто пропустит итерацию. |
| Feature flag = false / unset | Поведение = текущее prod (PR #28). |
| Strict + fallback оба False | Существующая fall-through логика к audio-dialog handler / overlay handler. |
| `_music_rights_just_accepted_iter is None` при следующем publish'е | Сбрасывается в `publish_tiktok` start — нет state leak между task'ами. |

---

## Testing

Расширяем `tests/test_publisher_tt_music_rights.py`:

| Test | Фикстура | Ожидаемо |
|---|---|---|
| `test_detect_fallback_matches_substring_title_lowercase` | XML с `text="music usage rights confirmation"` + checkbox-label EXACT + button EXACT + bounds overlap | fallback returns True |
| `test_detect_fallback_matches_substring_title_titlecase` | XML с `text="Music Usage Rights Confirmation"` + checkbox-label + button EXACT (Codex round 1, P2#4: case-insensitive) | fallback returns True |
| `test_detect_fallback_no_button_no_match` | XML с substring + checkbox-label но без button-node EXACT | fallback returns False |
| `test_detect_fallback_no_checkbox_label` | XML с substring + button EXACT но без _CHECKBOX EXACT label (только generic checkbox) | fallback returns False (Codex round 2, P1#1: generic-checkbox path удалён — false-positive risk) |
| `test_detect_fallback_bounds_not_in_same_dialog` | XML с substring + checkbox-label + button EXACT, но bounds **далеко** (>200px по Y) | fallback returns False (Codex round 2, P1#1: structural single-dialog requirement) |
| `test_detect_fallback_no_substring` | XML без указанных substring'ов | fallback returns False |
| `test_evidence_only_substring_no_button_triggers_dump` | XML с substring 'music rights' + generic checkbox, без EXACT button | `_detect_evidence_only` returns True; handler dump'ит XML с suffix `button_changed_suspect`; возвращает False |
| `test_strict_still_primary` | EXACT title XML | strict returns True; fallback не вызывается |
| `test_handle_with_fallback_writes_dump` | mock fallback match + `tmp_path` для dump | XML файл создаётся; log_event с `matched_via='fallback'`; filename содержит timestamp |
| `test_handle_creates_dump_dir_if_missing` | удалить `/tmp/autowarm_ui_dumps/` перед вызовом + mock fallback match | dump-файл создан, директория создана автоматически (Codex round 1, P2#7) |
| `test_post_music_rights_success_requires_three_iters_streak` | mock: iter+3 single good observation | streak=1, `upload_confirmed=False`. На iter+4 streak=2, iter+5 streak=3 → success (Codex round 2, P1#2: 3-iter threshold) |
| `test_post_music_rights_streak_resets_on_bad_iter` | mock: iter+3 good, iter+4 composer обратно → iter+5 good | streak=1→0→1; не triggers success (защита от транзита) |
| `test_post_music_rights_failure_hint_blocks_success` | mock: `MainActivity` есть, composer нет, но в ui есть `'Не удалось опубликовать'` | `is_good_iter=False`, streak=0 (Codex round 1, P1#2: failure-toast guard) |
| `test_post_music_rights_upload_in_progress_blocks_success` | mock: `MainActivity` + 'Загружается' в ui | `is_good_iter=False` (Codex round 2, P1#2: queued state guard) |
| `test_post_music_rights_no_success_composer_on_stack` | mock: `MainActivity` + `SAASceneWrapperActivity` в стеке | success-check не triggers |
| `test_post_music_rights_no_success_tiktok_not_active` | mock: `tiktok_active=False` | success-check не triggers |
| `test_post_music_rights_iters_since_below_3_skipped` | mock: iter+1 и iter+2, всё «good» | streak не инкрементируется (минимум iter+3 — Codex round 2, P1#2) |
| `test_post_music_rights_dump_at_iters_with_ms_timestamp_uuid` | mock: проходим iter 1,3,5; `TT_DUMP_POST_MUSIC_RIGHTS_XML=true` | dump-файлы созданы для каждого; filename содержит ms-timestamp + uuid suffix (Codex round 1, P3#9 + round 2, P3#1) |
| `test_dump_flag_off_no_writes` | `TT_DUMP_POST_MUSIC_RIGHTS_XML=false` (default) | dump-файлы не создаются — соответствует «flag=false = current prod» (Codex round 1, P1#1) |
| `test_feature_flag_off_fallback_skipped` | `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=false` | fallback не вызывается даже при substring match; evidence-only тоже не вызывается |
| `test_feature_flag_off_post_music_rights_skipped` | `TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED=false` | activity-check не triggers |
| `test_music_rights_iter_counter_reset_after_handled` | mock: 2 detections подряд, accept после 2-й | после accept `_music_rights_iter` сброшен → MAX_MUSIC_RIGHTS_ITERATIONS не preempt'ит post-accept фазу (Codex round 1, P1#3) |
| `test_music_rights_accepted_state_reset_between_publishes` | две последовательные `publish_tiktok` calls | `_music_rights_just_accepted_iter`, `_post_mr_good_streak` сбрасываются на старте каждого |

Все тесты — pytest, без live ADB (mock через monkeypatch).

---

## Live verification

### Smoke (phone #19 testbench)

1. Cherry-pick fix-commit в worktree, deploy через PM2 restart.
2. Запустить 2-3 re-queue для одного из недавних RC-A failed task'ов (4536) — проверить fallback fires; XML dump сохранён.
3. Запустить re-queue для RC-B failed task (4542) — проверить activity-check fires если publish реально прошёл.

Если testbench недоступен / Pi 9 orphan не resolved — деплой сразу в prod за flag'ом `false`, активация через `pm2 set` после smoke на следующий же publish с music-rights detected треком.

### Прод-rollout

**Активация env-vars — через `.env` файл + `pm2 restart --update-env`** (Codex round 2, P2#2: `pm2 set` устанавливает PM2-global, НЕ `os.environ` для процессов; код читает `os.environ`, поэтому нужно либо `.env` через ecosystem-config dotenv loader, либо явный `restart --update-env`).

Точные шаги:

1. Deploy кода с **тремя** flag'ами `false` (defaults). Smoke green (pytest pass).
2. Активировать инструментацию:
   ```bash
   cd /root/.openclaw/workspace-genri/autowarm
   # добавить строку в .env (создать если нет):
   echo "TT_DUMP_POST_MUSIC_RIGHTS_XML=true" >> .env
   pm2 restart autowarm --update-env
   ```
   Накапливаем XML evidence 1-2 часа на любом publish который пройдёт music-rights handler successfully.
3. Включить fallback matcher:
   ```bash
   echo "TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true" >> .env
   pm2 restart autowarm --update-env
   ```
4. Включить post-music-rights success-check:
   ```bash
   echo "TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED=true" >> .env
   pm2 restart autowarm --update-env
   ```
5. Мониторинг 4-6 часов:
   - Считаем events: `tt_music_rights_fallback_match`, `tt_upload_confirmed_post_music_rights`, `tt_music_rights_button_changed_suspect`.
   - Targeted query (Codex round 2, P2#3 — refined gate, не задеваемый unrelated timeouts):
     ```sql
     -- task'и с successful accept + последующим timeout БЕЗ промежуточного
     -- UPLOAD_OK event'а. Этот subset = RC-B fail; ожидание = 0.
     SELECT id FROM publish_tasks
     WHERE platform='TikTok' AND created_at > NOW() - INTERVAL '24 hours'
       AND error_code='tt_upload_confirmation_timeout'
       AND events @> '[{"meta": {"category": "tt_music_rights_accepted"}}]'::jsonb
       AND NOT EXISTS (
         SELECT 1 FROM jsonb_array_elements(events) e
         WHERE e->'meta'->>'category' LIKE 'tt_upload_confirmed%'
       );
     ```
   - Считаем false-positive: `tt_upload_confirmed_post_music_rights` но task потом завершилась как `publish_failed_*` или контент не появился в feed'е → false-positive.

### Если за 6 часов 0 успехов через post-music-rights detection и >=1 fallback-match XML сохранён

Exit rollout, читаем XML, итерируем дизайн на основе реальных данных (расширение activity list / UPLOAD_OK markers / button-text константы).

---

## Rollback

- Симметричный к rollout: `pm2 set` flag'и → `false`, поведение возвращается к PR #28.
- Если код-баг (например, исключение в fallback ломает publish целиком) — `git revert <commit>`, push, prod re-pull через auto-push hook.
- XML dump'ы остаются на `/tmp/` (одноразовые артефакты, не критично).

---

## Параллельная безопасность

- Работа в worktree `feat/tt-music-rights-coverage-and-post-accept-20260511` (memory `feedback_parallel_claude_sessions`).
- `git fetch origin` + sync с main перед стартом.
- pytest зелёный перед каждым commit (atomic commits, no half-broken).
- НЕ force-push на main (memory `feedback_subagent_force_push_risk`).

---

## Открытые вопросы (для plan stage)

1. **Phone #19 / Pi 9 orphan статус** — может ли smoke реально пройти на testbench, или сразу в prod за flag'ом? (Pi 9 orphan был блокером для TT 24h verify в `project_tt_post_publish_success_shipped`.)
2. **`task_id` доступность в publisher instance** — verified в RC-A.2: `self.task_id` уже используется в `publisher_tiktok.py:1502` (audio dialog dumps). Безопасно референсить.
3. **MAX_MUSIC_RIGHTS_ITERATIONS interaction** — закрыт через RC-B.2 (reset `_music_rights_iter = 0` после `handled=True`). Plan-stage: явный test (`test_music_rights_iter_counter_reset_after_handled`) валидирует.
