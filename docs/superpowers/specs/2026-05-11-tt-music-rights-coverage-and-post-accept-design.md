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

- **0** events `tt_upload_confirmation_timeout` следом за `tt_music_rights_accepted=true` в течение последующих 24h после rollout.
- **≥3** events `tt_music_rights_fallback_match` за первые 24h после включения fallback flag'а — подтверждение, что fallback ловит ранее пропускавшиеся диалоги.
- **≥3** events `tt_upload_confirmed_post_music_rights` — подтверждение, что activity-based success-check работает.

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
| `TT_DUMP_POST_MUSIC_RIGHTS_XML` | `true` | RC-B: per-iteration XML dump после accept (чистая инструментация, без логики) |

При flag=false поведение идентично текущему prod (PR #28). Любая активация — одной env-var, выключение симметрично.

### Точки изменений

| # | Где | Что |
|---|---|---|
| **RC-A.1** | `_detect_tt_music_rights_dialog` (стр. 209-257) | Новый метод `_detect_tt_music_rights_dialog_fallback(ui_xml) -> bool` |
| **RC-A.2** | `_handle_tt_music_rights_dialog` (стр. 347-389) | Hybrid invoke: сначала strict, если False и flag enabled — fallback. На fallback-match: сохранить полный XML + log_event с `matched_via='fallback'` |
| **RC-B.1** | `publish_tiktok` (стр. 391+) | Сброс `_music_rights_just_accepted_iter = None` и `_music_rights_accepted_ts = None` в начале (рядом с `_music_rights_iter = 0`) |
| **RC-B.2** | Upload-confirmation loop, в ветке `if handled: time.sleep(2); continue;` (стр. 922-924) | Set `_music_rights_just_accepted_iter = wait` и `_music_rights_accepted_ts = time.time()` |
| **RC-B.3** | Тот же loop, после `tiktok_active` блока (~стр. 798+), но до UPLOAD_OK substring check | Активный activity-based success-check (см. ниже) |
| **RC-B.4** | Тот же loop | Per-iteration XML dump после accept (логарифмическая частота) |

Не трогаем: AI Unstuck, MAX_* константы, существующие markers (EXACT), audio-dialog handler, music_rights_stuck cap.

---

## Детальный дизайн

### RC-A.1: Fallback matcher

```python
def _detect_tt_music_rights_dialog_fallback(self, ui_xml: str) -> bool:
    """Looser match для случаев когда TT обновил title-текст.

    Срабатывает ТОЛЬКО когда strict _detect_tt_music_rights_dialog вернул
    False. Условия match (ВСЕ должны быть true):

    1. Substring pre-filter (case-sensitive): в ui_xml есть одна из
       _TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS.
    2. Структурная проверка через XML parse:
       a) has_specific_structure (checkbox-label OR button EXACT) OR
          has_generic_checkbox (checkable=true / class*=CheckBox)
       b) И clickable-button-node с text/desc EXACT in
          _TT_MUSIC_RIGHTS_BUTTON (=кнопка accept в досягаемости).

    Условие (2b) — анкер «правильного» диалога: без EXACT-кнопки accept мы не
    считаем match (защита от false-positive на экранах где «music rights»
    появляется в caption/captions/hashtag).
    """
```

Константа:
```python
_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS = [
    'права на использование музыки',
    'music usage rights',
    'music rights',
    'rights confirmation',
    'подтверждение прав',
]
```

Возвращает `True` ⟺ substring найден AND (specific structure OR generic checkbox) AND button accept присутствует. Иначе `False`.

### RC-A.2: Hybrid invocation в `_handle_tt_music_rights_dialog`

```python
def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
    matched_via = None
    if self._detect_tt_music_rights_dialog(ui_xml):
        matched_via = 'strict'
    elif (os.environ.get('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'false').lower() == 'true'
          and self._detect_tt_music_rights_dialog_fallback(ui_xml)):
        matched_via = 'fallback'
        dump_path = self._save_dump_for_fallback_review(ui_xml)
        self.log_event(
            'info',
            'TikTok: music rights dialog matched via fallback',
            meta={'category': 'tt_music_rights_fallback_match',
                  'dump_path': dump_path,
                  'platform': self.platform})
    else:
        return False

    # ... existing tick + tap flow ...
    # log_event meta получает 'matched_via': matched_via
```

`_save_dump_for_fallback_review` — best-effort write в `/tmp/autowarm_ui_dumps/tt_music_rights_fallback_<task_id>_<ts>.xml`. Возвращает путь или `'write_failed'`. Никогда не raise'ит — на любой exception log warning и продолжаем.

### RC-B.3: Activity-based success-check (внутри upload-confirmation loop)

```python
# Вставка после блока `tiktok_active` проверки (~стр. 798), до UPLOAD_OK substring check.
if (os.environ.get('TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED', 'false').lower() == 'true'
    and self._music_rights_just_accepted_iter is not None
    and tiktok_active):

    iters_since = wait - self._music_rights_just_accepted_iter
    if iters_since >= 1:  # дать TT минимум 1 итерацию = ~3 сек на transition
        composer_on_stack = (
            'SAASceneWrapperActivity' in act
            or 'reels_editor' in ui
            or 'clips_creation' in ui
            or any(m in ui for m in STILL_ON_EDITOR)
        )
        post_publish_activity = any(a in act for a in (
            'MainActivity', 'DetailActivity',
            'ProfileActivity', 'UserProfileActivity',
        ))
        if post_publish_activity and not composer_on_stack:
            log.info(f'  ✅ TikTok: post-music-rights navigate-away (iter+{iters_since})')
            self.log_event('info',
                'TikTok: публикация подтверждена (post-music-rights activity)',
                meta={'category': 'tt_upload_confirmed_post_music_rights',
                      'topActivity': act.strip()[:120],
                      'iters_after_accept': iters_since})
            upload_confirmed = True
            break
```

**Guards:**
- `tiktok_active=True` обязателен (защита от overlay / hijack).
- `composer_on_stack=False` обязателен (защита от false-positive когда `MainActivity` лежит в стеке под composer'ом).
- `iters_since >= 1` (~3 сек) — даём TT транзишн.

### RC-B.4: Per-iteration XML dump

```python
if (os.environ.get('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'true').lower() == 'true'
    and self._music_rights_just_accepted_iter is not None):

    iters_since = wait - self._music_rights_just_accepted_iter
    if iters_since in (1, 3, 5, 10, 20, 40):  # логарифмическая частота
        try:
            path = (f'/tmp/autowarm_ui_dumps/'
                    f'tt_post_music_rights_{self.task_id}_iter{iters_since}.xml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ui or '')
            log.info(f'  💾 post-music-rights dump (iter+{iters_since}): {path}')
        except Exception as e:
            log.warning(f'  ⚠️ Не удалось сохранить post-music-rights dump: {e}')
```

Активна по умолчанию (флаг `TT_DUMP_POST_MUSIC_RIGHTS_XML=true`). Цель — собрать XML evidence для следующей итерации (если RC-B не покрывается activity-check'ом).

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
| `test_detect_fallback_matches_substring_title` | XML с `text="Music usage rights confirmation"` + checkbox + button EXACT | fallback returns True |
| `test_detect_fallback_no_button_no_match` | XML с substring но без `Опубликовать видео`/`Publish video` button-node | fallback returns False |
| `test_detect_fallback_no_substring` | XML без указанных substring'ов | fallback returns False |
| `test_strict_still_primary` | EXACT title XML | strict returns True; fallback не вызывается |
| `test_handle_with_fallback_writes_dump` | mock fallback match + `tmp_path` для dump | XML файл создаётся; log_event с `matched_via='fallback'` |
| `test_post_music_rights_success_main_activity` | mock: после accept iter+2, `topActivity` содержит `MainActivity`, composer отсутствует | `upload_confirmed=True`; event `tt_upload_confirmed_post_music_rights` |
| `test_post_music_rights_no_success_composer_on_stack` | mock: `MainActivity` есть + `SAASceneWrapperActivity` тоже в стеке | success-check не срабатывает |
| `test_post_music_rights_no_success_tiktok_not_active` | mock: `tiktok_active=False` | success-check не срабатывает |
| `test_post_music_rights_dump_at_iters` | mock: проходим iter 1,3,5 | dump-файлы созданы для каждого |
| `test_feature_flag_off_fallback_skipped` | `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=false` | fallback не вызывается даже при substring match |
| `test_feature_flag_off_post_music_rights_skipped` | `TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED=false` | activity-check не срабатывает |
| `test_music_rights_accepted_state_reset_between_publishes` | две последовательные `publish_tiktok` calls | `_music_rights_just_accepted_iter` сбрасывается на старте каждого |

Все тесты — pytest, без live ADB (mock через monkeypatch).

---

## Live verification

### Smoke (phone #19 testbench)

1. Cherry-pick fix-commit в worktree, deploy через PM2 restart.
2. Запустить 2-3 re-queue для одного из недавних RC-A failed task'ов (4536) — проверить fallback fires; XML dump сохранён.
3. Запустить re-queue для RC-B failed task (4542) — проверить activity-check fires если publish реально прошёл.

Если testbench недоступен / Pi 9 orphan не resolved — деплой сразу в prod за flag'ом `false`, активация через `pm2 set` после smoke на следующий же publish с music-rights detected треком.

### Прод-rollout

1. Deploy кода с **обоими** flag'ами `false`. Smoke green (тесты pass).
2. Включить `TT_DUMP_POST_MUSIC_RIGHTS_XML=true` (default — уже true, но verify). Накапливаем XML evidence 1-2 часа на любом publish который пройдёт music-rights handler successfully.
3. Включить `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true`.
4. Включить `TT_POST_MUSIC_RIGHTS_DETECTION_ENABLED=true`.
5. Мониторинг 4-6 часов:
   - Считаем events: `tt_music_rights_fallback_match`, `tt_upload_confirmed_post_music_rights`.
   - Не должно быть `tt_upload_confirmation_timeout` сразу после `tt_music_rights_accepted=true`.
   - Считаем false-positive: `tt_upload_confirmed_post_music_rights` но task с downstream `publish_failed_*` (= мы зафиксировали success там где не было).

### Если за 6 часов 0 успехов через post-music-rights detection и >=1 fallback-match XML сохранён

Exit rollout, читаем XML, итерируем дизайн на основе реальных данных (второй раунд: расширение activity list или новые UPLOAD_OK markers).

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
2. **MAX_MUSIC_RIGHTS_ITERATIONS** — может ли cap (5) перебивать post-music-rights detection? Если activity-check fires до 5-й итерации после accept — нет проблем. Если позже — может произойти `tt_music_rights_stuck` exit раньше. Plan-stage: проверить, возможен ли scenario «5-й iter dialog detected, но post-music-rights activity-check ещё не fires».
3. **`task_id` доступность в publisher instance** — для имён dump-файлов нужен `self.task_id` или эквивалент. Plan: проверить какое поле использовать (возможно `self.publish_task_id`).
