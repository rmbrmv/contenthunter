# TT Music-Rights Coverage + Post-Accept Success Detection — Design

**Дата:** 2026-05-11
**Автор:** Claude (Opus 4.7 1M)
**Триггер:** Регрессия после ship'а music-rights handler (PR #28, commit `8ec5c53`, merged 2026-05-10). Метрика: **0 успешных публикаций TT с music-rights диалогом за 72 часа**; `tt_upload_confirmation_timeout` = 7 fails / 24h.
**Связанные документы:**
- `docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md` (PR #28 spec — music rights handler)
- `docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md` (PR #29 — `_tt_infer_post_publish_success`)
- Memory: `project_tt_music_rights_dialog_shipped`, `project_tt_post_publish_success_shipped`, `reference_tt_activities_observed`, `feedback_publisher_error_code_misleading`

**v6 (2026-05-11):** REWRITE для интеграции с PR #29. После обнаружения `_tt_infer_post_publish_success` (shipped 09:55 MSK) пытались добавить streak-guard как defensive layer. Codex round 1 нашёл P1: streak-gate бесполезен если detector возвращает False (что и происходит у всех 3 post-PR#29 failed task'ов).

**v7 (2026-05-11): scope-cut RC-B.** Без XML evidence невозможно honestly спроектировать positive-path detection для post-music-rights screen — это будет угадывание. Поэтому ship'аем то, что точно работает (RC-A matcher + RC-B.0 SEED-fix + RC-B.4 instrumentation), instrumentation собирает evidence, второй раунд проектирует RC-B detection с реальными dump'ами.

**Reality check failed tasks vs PR #29:** 3 task'а после PR #29 deploy (06:55 UTC 2026-05-11) — 4643, 4641 имеют `tt_music_rights_accepted=true` и НЕ имеют `tt_post_publish_success_inferred=true` → detector существует но не triggers для music-rights state. Поэтому RC-B detection требует evidence, а не угадывания.

---

## Проблема

После ship'а music-rights handler (PR #28) production-метрика по TT-публикациям регрессировала. Из 5 свежайших failed task'ов за 24 часа выявлены два независимых root cause:

### RC-A — Handler не срабатывает (≈40% timeout'ов: tasks 4536, 4488, 4482)

Music-rights диалог появляется на экране (AI Unstuck визуально его видит и вручную пытается тапнуть `music rights`), но `_detect_tt_music_rights_dialog` возвращает `False`. Причины:
- Strict matcher требует **EXACT** match по title-node против 4 заранее зафиксированных вариантов (`'Подтвердить и опубликовать видео?'` / `'Confirm and publish video'` ± `?`).
- TT минорно обновил UI: либо новый текст title-node, либо изменилась XML-структура (title-text оказался в desc или в sub-node), и EXACT не matches.
- UI dump'ы для failed tasks **не сохраняются** в текущем коде на этой ветке — точное содержимое нового XML неизвестно.

### RC-B — Handler сработал, но post-accept screen не появляется (≈60%: tasks 4542, 4541, 4540, 4539)

Event `tt_music_rights_accepted` с `button_tapped=true` залогирован успешно. Через ~30-50 сек AI Unstuck триггерит «An unexpected screen is blocking upload confirmation». UPLOAD_OK substring markers (`Загружается`, `Для вас`, `DetailActivity`, `Опубликовано` и т.д.) не matches в течение 3-минутного timeout-loop'а.

**Две sub-моды RC-B** (Codex round 4, P1#1 — без XML evidence невозможно определить долю каждой):

- **B1: navigate-away в неизвестный экран.** TT покинул composer, попал в screen которого UPLOAD_OK substring markers не покрывают (новый промежуточный screen, новый текст «Обрабатывается», или unfamiliar activity). **Этот fix адресует B1** через activity-based detection — мы видим navigate-away и confirm'им success.
- **B2: TT остался в composer (`SAASceneWrapperActivity` стек) — публикация реально провалилась.** В этом случае никакой ПЕЧАТЬ-side детектор не «спасёт» публикацию (она genuinely не произошла). Наш fix B2 НЕ адресует — но instrumentation (XML dump на каждой итерации) даст evidence для следующего раунда (например, retry-on-composer-stuck или вызов AI Unstuck с более конкретным промптом).

Без сохранённого XML мы не можем гарантированно посчитать долю B1 vs B2. Это критично — отсюда требование инструментации. Метрика отражает это: rate-based, target ≥80% задач завершают успешно, **не 100%** (B2 случаи останутся fail'ами до следующего раунда).

### Метрика успеха

(Codex round 1, P2#8: rate-based, не traffic-зависимая абсолюта.)

**v7 scope-cut: RC-B success rate НЕ адресуется** — будет вторым раундом после XML evidence.

Текущая итерация цели:
- **RC-A coverage:** Доля task'ов с `tt_music_rights_accepted=true` среди failed RC-A-cases должна вырасти. Считаем `tt_music_rights_fallback_match` events за 24h — каждый event = ранее упускавшийся matcher case теперь покрыт. Win condition: **≥1 event за первые 24h** (= новый покрытый case validated). Если 0 за 24h при наличии `tt_music_rights_unhandled_suspect` events → fallback слишком строгий, расследуем suspect XML. Если 0 за 24h и 0 suspect → TT стабилизировал title text (RC-A исчерпан, fix profilactic).
- **RC-A false-positives:** 0 events `tt_music_rights_unhandled_suspect` followed by downstream `publish_failed_generic` с UI XML show no actual music-rights dialog. (Manual review evidence-only XML's за 24h.)
- **RC-B.0 SEED hardening side-effect:** монитор `tt_post_publish_success_inferred` rate — не должен УПАСТЬ значительно (SEED expansion может убрать прежние false-positives). Если падение >10% — расследуем.
- **Evidence для следующего раунда:** ≥5 XML dump'ов сохранены для failed tasks с `mr_accept=true, pp_inferred=false`. Это input для design'а RC-B.3 v2.

---

## Скоп

**В скопе:**
- Изменения в `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`.
- Расширение тестов в `tests/test_publisher_tt_music_rights.py`.
- Три feature flag'а для постепенной активации (см. таблицу в Архитектура).

**Не в скопе:**
- Изменения strict `_detect_tt_music_rights_dialog` (остаётся primary).
- Изменения `_strict_tap_clickable`, `_tick_tt_music_rights_checkbox` (рабочие).
- Изменения `_TT_MUSIC_RIGHTS_TITLE_MARKERS`/`_BUTTON`/`_CHECKBOX` константы (расширение — отдельная задача после анализа собранных XML dump'ов).
- AI Unstuck изменения (separate concern).
- `tt_fg_lost` (отдельный backlog, task 4523).
- **Замена `_tt_infer_post_publish_success` (PR #29)** — РАСШИРЯЕМ, не переписываем (v6: интеграция вместо дублирования).

---

## Архитектура

Один файл — `publisher_tiktok.py`. **Подход v7 (scope-cut):** ship narrow set с реальной evidence-backed value:
- RC-A matcher coverage (RC-A.1, RC-A.1b, RC-A.2) — closes RC-A ~40%
- RC-B.0 SAASceneWrapperActivity → SEED — closes known SEED hole для всех TT publish'ей
- RC-B.4 per-iteration XML dump после music_rights accept — instrumentation для следующего раунда

RC-B success-path detection (60% timeouts) **намеренно НЕ адресуется в этом раунде** — без XML evidence design будет угадыванием. Instrumentation соберёт данные, второй раунд spec'а спроектирует positive-path detection.

Три feature-flag'а:

| Flag | Default | Покрытие |
|---|---|---|
| `TT_MUSIC_RIGHTS_FALLBACK_ENABLED` | `false` | RC-A: fallback matcher + dump XML на fallback-match |
| `TT_SEED_HARDENING_SAASCENE_ENABLED` | `false` | RC-B.0: добавить `SAASceneWrapperActivity` в SEED (Codex v10 round 1, P2: gate'им; если TT использует wrapper не только в composer — может suppress'нуть valid detections) |
| `TT_DUMP_POST_MUSIC_RIGHTS_XML` | `false` | RC-B.4: per-iteration XML dump после accept (инструментация, opt-in) |

При **всех** flag=false поведение идентично prod (PR #28 + PR #29). Все три изменения полностью opt-in — pure no-op rollout по default (Codex v10 round 1, P2: исправлено).

**Evidence-guarded activation для SEED hardening:** flag включается ПОСЛЕ того как dumps от RC-B.4 покажут что SAASceneWrapperActivity реально присутствует на failed post-music-rights screens (= confirmed composer use-case). До этого — flag off, SEED не расширяется. Это защита от случая если TT использует wrapper для post-publish/feed screens — тогда добавление в SEED suppress'нёт valid `_tt_infer_post_publish_success` detections.

### Точки изменений

| # | Где | Что |
|---|---|---|
| **RC-A.1** | `_detect_tt_music_rights_dialog` (стр. 209-257) | Новый метод `_detect_tt_music_rights_dialog_fallback(ui_xml) -> bool` |
| **RC-A.1b** | Same area | Новый метод `_detect_tt_music_rights_dialog_evidence_only(ui_xml) -> bool` — evidence-only path |
| **RC-A.2** | `_handle_tt_music_rights_dialog` (стр. 347-389) | Hybrid invoke: strict → fallback → evidence-only |
| **RC-B.0 (flag-gated)** | `TT_COMPOSER_ACTIVITIES_SEED` (стр. 53-62) | Добавить `'SAASceneWrapperActivity'` в tuple **через runtime branch** (не статическая константа): `if TT_SEED_HARDENING_SAASCENE_ENABLED: composer_check = SEED + ('SAASceneWrapperActivity',) else: composer_check = SEED`. Применяется внутри `_tt_infer_post_publish_success`. По default flag=false — поведение прежнее. |
| **RC-B.1** | `publish_tiktok` (стр. 391+) | Сброс `_music_rights_just_accepted_iter = None`, `_music_rights_accepted_ts = None`, `_music_rights_evidence_dumped = False` в начале (рядом с `_music_rights_iter = 0`) |
| **RC-B.2** | Upload-confirmation loop, в ветке music-rights `if handled: time.sleep(2); continue;` (стр. 922-924, где `handled = self._handle_tt_music_rights_dialog(ui)`) | Set `_music_rights_just_accepted_iter = wait` и `_music_rights_accepted_ts = time.time()`. **Также:** reset `_music_rights_iter = 0` (декаплинг counter'а от post-accept фазы) |
| **RC-B.4** | Upload-confirmation loop | Per-iteration XML dump после music_rights accept (логарифмическая частота, opt-in) |

Не трогаем: AI Unstuck, MAX_* константы, existing markers (EXACT), audio-dialog handler, `_tt_infer_post_publish_success` (после v7 scope-cut — даже caller-side gating отложен до evidence-based раунда).

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
       c) (a) и (b) находятся **в общем dialog-контейнере** (Codex round 4,
          P2#4 + Codex v7 round 1, P2#1). Bounds-overlap ±200px фрагилен;
          generic `FrameLayout`/`LinearLayout`/`RelativeLayout` слишком
          broad (могут collapse'ить к composer root). Используем strict
          ancestry-based check: подняться по родителям от node-(a) и
          от node-(b), найти общий ancestor; ancestor должен иметь
          class содержащий **только** `'Dialog'`, `'PopupWindow'` или
          `'AlertDialog'` (не generic layouts). Если общий ancestor не
          найден за 8 уровней или это generic layout — fallback fails
          (evidence-only path подхватит для логирования).

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

Возвращает `True` ⟺ lowercase substring найден AND checkbox-label EXACT AND clickable button EXACT AND common dialog ancestor. Иначе `False`. (Codex round 2, P1#1 + round 3, P2#1: legacy формула `specific structure OR generic checkbox` устранена; Codex round 4, P2#4: bounds-overlap fragile, заменён ancestry-based.)

### RC-A.1b: Evidence-only fallback (без auto-handle)

Для случая когда TT поменял **и** title **и** button-текст (Codex round 1, P2#5: «button EXACT» — точка хрупкости). Дополнительный, более слабый detector:

```python
def _detect_tt_music_rights_dialog_evidence_only(self, ui_xml: str) -> bool:
    """Slack-match только для логирования + dump.

    Условия (Codex round 4, P2#2 — расширено: ранее требовался NOT-button,
    что упускало кейсы где button EXACT нашёлся но checkbox/title менялись):
      1. Substring 'music rights' / 'права … музыки' в lowercase ui_xml.
      2. has_generic_checkbox в дереве (`checkable='true'` OR class*=CheckBox).
      3. Caller проверил что strict И fallback оба вернули False
         (детектор сам этого не знает — это logical-AND на уровне caller'а).

    НЕ возвращает True для auto-accept. Caller использует этот сигнал
    только чтобы dump XML и залогировать suspect-event — фикс будет
    после ручного review dump'а.
    """
```

В `_handle_tt_music_rights_dialog`:
- Если strict-fallback оба False, но `_detect_tt_music_rights_dialog_evidence_only` True → `log_event('warning', ..., meta={'category': 'tt_music_rights_unhandled_suspect', ...})` + dump XML. Возвращает `False` (не handle'им — даём fall-through существующей логике).

**Throttle (Codex v7 round 1, P3#1):** persistent suspect screen может triggered evidence-only path на каждой iteration upload-confirmation loop (60 iter × 3 sec). Чтобы не спамить /tmp + events:
- Per-task instance flag `self._music_rights_evidence_dumped = False` (init в `publish_tiktok` start).
- evidence-only path выполняет dump+log **только если** `not self._music_rights_evidence_dumped`. После first dump — set `= True`, последующие detections silent fall-through.

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
        # Evidence-only path: strict+fallback оба False, но evidence-only
        # детектор matches. Не handle'им — только dump + log. Throttle через
        # per-task flag (Codex v7 round 1, P3#1; round 2, P3#3 — throttle
        # явно в pseudocode + тестах).
        if (fallback_enabled
            and not getattr(self, '_music_rights_evidence_dumped', False)
            and self._detect_tt_music_rights_dialog_evidence_only(ui_xml)):
            dump_path = self._save_dump_for_fallback_review(
                ui_xml, suffix='unhandled_suspect')
            self.log_event(
                'warning',
                'TikTok: music rights-like dialog suspect, not auto-handled',
                meta={'category': 'tt_music_rights_unhandled_suspect',
                      'dump_path': dump_path,
                      'platform': self.platform})
            self._music_rights_evidence_dumped = True  # throttle
        return False

    # ... existing tick + tap flow ...
    # log_event meta получает 'matched_via': matched_via
```

`_save_dump_for_fallback_review(ui_xml, suffix)`:
- Создаёт директорию `/tmp/autowarm_ui_dumps/` через `os.makedirs(..., exist_ok=True)` (Codex round 1, P2#7).
- Имя файла: `tt_music_rights_{suffix}_{task_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.xml` — миллисекундный timestamp + короткий random suffix защищают от коллизии при retries в тот же sec (Codex round 1, P3#9; Codex round 2, P3#1).
- Best-effort write. На exception — `log.warning(...)` и возврат `'write_failed'`. Никогда не raise'ит.

### RC-B.0: Flag-gated SEED hardening (v10)

**Не статическое расширение SEED**, а runtime branch (Codex v10 round 1, P2: SAASceneWrapperActivity может использоваться в TT не только в composer; гипотеза untested, поэтому evidence-guarded).

Изменение в `_tt_infer_post_publish_success` (стр. 78-150):

```python
import os as _os

def _tt_infer_post_publish_success(ui, top_activity, wait_iter):
    # ... existing code до on_composer check ...

    # Build composer-activity set conditionally based on flag.
    seed = TT_COMPOSER_ACTIVITIES_SEED
    if _os.environ.get('TT_SEED_HARDENING_SAASCENE_ENABLED', 'false').lower() == 'true':
        seed = seed + ('SAASceneWrapperActivity',)

    on_composer = any(a in cur_act for a in seed)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        meta['reason'] = 'on_composer_seed'
        return False, meta
    # ... existing code продолжает ...
```

**Rationale:** memory `reference_tt_activities_observed` зафиксирована наблюдаемая activity. Если flag enabled И TT реально показывает SAASceneWrapperActivity на post-music-rights screen → detector корректно говорит «composer, не success». Если TT использует wrapper в feed/profile тоже → flag не активируется до сбора evidence из dump'ов.

**Активация:** только после того как ≥1 XML dump от RC-B.4 instrumentation покажет `SAASceneWrapperActivity` присутствует на failed post-accept screen. До этого — flag off.

### RC-B.3: ОТЛОЖЕНО до evidence-based раунда

**v7 scope-cut.** Изначальный дизайн (streak-gate + anti-signals на `_tt_infer_post_publish_success`) был P1-rejected Codex'ом round 1 на v6 (см. история):

> Streak-guard cannot improve missed detections if `_tt_infer_post_publish_success` returns `False`. The observed failed tasks have no `tt_post_publish_success_inferred`; adding a gate only delays/blocks `True` results, it does not make PR #29 detect new post-accept screens.

Failed tasks (4643, 4641, 4636 после PR #29 deploy) показывают что детектор возвращает False на post-music-rights screen — наш gate не может это починить, он работает только на True результатах.

**Что делаем вместо:**
- RC-B.0 (всегда on): `SAASceneWrapperActivity` → SEED. Закрывает known hole.
- RC-B.4 (opt-in flag): per-iteration XML dump после accept. Собирает evidence (что именно за screen TT показывает).
- Через 24-48h после rollout анализируем dump'ы; второй раунд spec'а проектирует positive-path detection с реальными данными.

Backlog item: после сбора dump'ов от ≥5 failed task'ов → analyze + design `_tt_infer_post_publish_success` extension (новые activities / nav-threshold lowering / supplemental detection path в music-rights context).

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

Default `false` (Codex round 1, P1#1) — opt-in активация в rollout step 2. Цель — собрать XML evidence для следующей итерации RC-B.3 design'а.

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
| `test_detect_fallback_matches_substring_title_lowercase` | XML с `text="music usage rights confirmation"` + checkbox-label EXACT + button EXACT + общий Dialog/PopupWindow ancestor | fallback returns True |
| `test_detect_fallback_matches_substring_title_titlecase` | XML с `text="Music Usage Rights Confirmation"` + checkbox-label + button EXACT (Codex round 1, P2#4: case-insensitive) | fallback returns True |
| `test_detect_fallback_no_button_no_match` | XML с substring + checkbox-label но без button-node EXACT | fallback returns False |
| `test_detect_fallback_no_checkbox_label` | XML с substring + button EXACT но без _CHECKBOX EXACT label (только generic checkbox) | fallback returns False (Codex round 2, P1#1: generic-checkbox path удалён — false-positive risk) |
| `test_detect_fallback_no_common_dialog_ancestor` | XML с substring + checkbox-label + button EXACT, но nodes под разными root-children (нет общего Dialog/PopupWindow ancestor за 8 уровней) | fallback returns False |
| `test_detect_fallback_with_common_dialog_ancestor` | XML где checkbox + button под общим `<node class="...AlertDialog">` на 3 уровне выше | fallback returns True |
| `test_detect_fallback_rejects_generic_layout_ancestor` | XML где общий ancestor — `FrameLayout`/`LinearLayout` (не Dialog class) | fallback returns False (Codex v7 round 1, P2#1: generic layouts collapse'ят к composer root) |
| `test_detect_fallback_no_substring` | XML без указанных substring'ов | fallback returns False |
| `test_evidence_only_substring_no_button_triggers_dump` | XML с substring 'music rights' + generic checkbox, без EXACT button | `_detect_evidence_only` returns True; handler dump'ит XML с suffix `unhandled_suspect`; возвращает False |
| `test_evidence_only_throttled_after_first_dump` | mock: 3 последовательных handler calls с suspect XML | dump + log fires только на 1-м; 2-й и 3-й — silent fall-through (Codex v7 round 1, P3#1) |
| `test_evidence_only_throttle_resets_between_publishes` | две последовательные `publish_tiktok` calls, в каждой suspect XML | dump + log fires в каждом publish'е (per-task state, сбрасывается на старте `publish_tiktok`) |
| `test_strict_still_primary` | EXACT title XML | strict returns True; fallback не вызывается |
| `test_handle_with_fallback_writes_dump` | mock fallback match + `tmp_path` для dump | XML файл создаётся; log_event с `matched_via='fallback'`; filename содержит timestamp |
| `test_handle_creates_dump_dir_if_missing` | удалить `/tmp/autowarm_ui_dumps/` перед вызовом + mock fallback match | dump-файл создан, директория создана автоматически (Codex round 1, P2#7) |
| `test_seed_hardening_flag_off_no_saascene` | flag=false, mock `_tt_infer_post_publish_success(top_activity='SAASceneWrapperActivity', ...)` | `on_composer_seed=False` (SEED unchanged) |
| `test_seed_hardening_flag_on_adds_saascene` | flag=true, тот же mock | `on_composer_seed=True`, `reason='on_composer_seed'` |
| `test_evidence_only_fires_when_button_exists_but_strict_and_fallback_fail` | XML с substring + generic checkbox + button EXACT, НО checkbox-label НЕ EXACT и title НЕ EXACT | strict=False, fallback=False, evidence-only=True → dump |
| `test_dump_at_iters_with_ms_timestamp_uuid` | mock: проходим iter 1,3,5 с music_rights_accepted; `TT_DUMP_POST_MUSIC_RIGHTS_XML=true` | dump-файлы созданы для каждого; filename содержит ms-timestamp + uuid suffix |
| `test_dump_flag_off_no_writes` | `TT_DUMP_POST_MUSIC_RIGHTS_XML=false` (default) | dump-файлы не создаются |
| `test_dump_only_after_music_rights_accept` | mock: publish_tiktok без music_rights detection + flag on | dump-файлы не создаются (gated `_music_rights_just_accepted_iter is not None`) |
| `test_feature_flag_off_fallback_skipped` | `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=false` | fallback не вызывается даже при substring match; evidence-only тоже |
| `test_music_rights_iter_counter_reset_after_handled` | mock: 2 detections подряд, accept после 2-й | после accept `_music_rights_iter` сброшен → MAX не preempt'ит post-accept фазу (Codex round 1, P1#3) |
| `test_music_rights_accepted_state_reset_between_publishes` | две последовательные `publish_tiktok` calls | `_music_rights_just_accepted_iter` сбрасывается на старте каждого |
| `test_existing_pr29_normal_publish_path_unchanged` | mock без music_rights events + `_tt_infer_post_publish_success`→success | success confirmed сразу — normal flow без regression (PR #29 не задеён) |

Все тесты — pytest, без live ADB (mock через monkeypatch).

---

## Live verification

### Smoke (phone #19 testbench)

1. Cherry-pick fix-commit в worktree, deploy через PM2 restart.
2. **Перед smoke включить флаги на testbench** (иначе fallback не сработает): set `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true` и `TT_DUMP_POST_MUSIC_RIGHTS_XML=true` в testbench .env, restart PM2. (Codex v9 round 1, P2: prod flags ≠ testbench flags.)
3. Запустить 2-3 re-queue для одного из недавних RC-A failed task'ов (4536) — проверить `tt_music_rights_fallback_match` ИЛИ `tt_music_rights_unhandled_suspect` event fires; XML dump сохранён.
4. Запустить re-queue для RC-B failed task (4542) — **только validation что spec не сломал normal flow** (publish либо прошёл через PR #29 detector как раньше, либо timed out — оба ожидаемы; main цель — сохранить `tt_post_music_rights_*.xml` dumps).

Если testbench недоступен / Pi 9 orphan не resolved — деплой сразу в prod за flag'ом `false`, активация через `.env` + `pm2 restart --update-env` после deploy.

### Прод-rollout

**Активация env-vars — через `.env` файл + `pm2 restart --update-env`** (Codex round 2, P2#2: `pm2 set` устанавливает PM2-global, НЕ `os.environ` для процессов; код читает `os.environ`, поэтому нужно либо `.env` через ecosystem-config dotenv loader, либо явный `restart --update-env`).

Точные шаги:

1. Deploy кода с **тремя** flag'ами `false` (defaults). Smoke green (pytest pass). Pure no-op rollout.
Все шаги idempotent (Codex round 3, P2#3 — `echo >>` мог дублировать ключ; `sed -i '/^KEY=/d'` сначала удаляет существующий, потом append):

2. Активировать инструментацию:
   ```bash
   cd /root/.openclaw/workspace-genri/autowarm
   sed -i '/^TT_DUMP_POST_MUSIC_RIGHTS_XML=/d' .env 2>/dev/null || true
   echo "TT_DUMP_POST_MUSIC_RIGHTS_XML=true" >> .env
   pm2 restart autowarm --update-env
   ```
   Накапливаем XML evidence 1-2 часа на любом publish который пройдёт music-rights handler successfully.
3. Включить fallback matcher:
   ```bash
   sed -i '/^TT_MUSIC_RIGHTS_FALLBACK_ENABLED=/d' .env 2>/dev/null || true
   echo "TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true" >> .env
   pm2 restart autowarm --update-env
   ```
3a. **Evidence-guarded** SEED hardening — активируется ТОЛЬКО после того как dump от step 2 покажет `SAASceneWrapperActivity` в `top_activity` на failed post-accept screen (= confirmed composer use-case, не feed/profile). Затем:
   ```bash
   sed -i '/^TT_SEED_HARDENING_SAASCENE_ENABLED=/d' .env 2>/dev/null || true
   echo "TT_SEED_HARDENING_SAASCENE_ENABLED=true" >> .env
   pm2 restart autowarm --update-env
   ```
   Если evidence не подтверждает (SAASceneWrapperActivity not seen, или seen на success screens) — SEED flag остаётся off, документируем backlog item.
4. Мониторинг 4-6 часов:
   - Считаем events: `tt_music_rights_fallback_match`, `tt_music_rights_unhandled_suspect`, `tt_post_publish_success_inferred` rate.
   - RC-A win condition: `tt_music_rights_fallback_match` count ≥ 1 (= ранее упущенный matcher case теперь покрыт). Если 0 за 24h при наличии failed task'ов — fallback слишком строгий, расследуем dumps.
   - SEED side-effect monitor: `tt_post_publish_success_inferred` rate (24h after vs 24h before) — drop > 10% значит SAASceneWrapperActivity в SEED убрала прежние true-positives. Если drop >10% — расследуем events `_tt_infer_post_publish_success` meta.
   - Через 24-48h: разобрать `/tmp/autowarm_ui_dumps/tt_post_music_rights_*.xml` для всех failed tasks с `mr_accept=true` без `tt_post_publish_success_inferred`. Это input для следующего раунда RC-B spec'а.
   - **Diagnostic query** (для дальнейшего analysis, не для gate'а):
     ```sql
     -- Failed task'и с music_rights accept + timeout + без tt_post_publish_success_inferred.
     -- v7 scope-cut: subset reflects unfixed RC-B; ожидание = some count > 0
     -- (это input для следующего раунда, не gate'ующая метрика).
     SELECT id, account, screen_record_url FROM publish_tasks
     WHERE platform='TikTok' AND created_at > NOW() - INTERVAL '24 hours'
       AND error_code='tt_upload_confirmation_timeout'
       AND events @> '[{"meta": {"category": "tt_music_rights_accepted"}}]'::jsonb
       AND NOT (events @> '[{"meta": {"category": "tt_post_publish_success_inferred"}}]'::jsonb)
     ORDER BY id DESC;
     ```

### Если за 6 часов 0 fallback-match events и >=1 button_changed_suspect XML

Exit rollout, читаем suspect XML, итерируем title/checkbox/button константы в следующем patch'е.

---

## Rollback

- Симметричный к rollout — через `.env` + `pm2 restart --update-env` (Codex round 3, P2#2: `pm2 set` не влияет на `os.environ`). Disable **оба** flag'а (Codex v9 round 1, P3#1: dump-flag тоже надо disable, иначе оставим instrumentation on after rollback):
  ```bash
  cd /root/.openclaw/workspace-genri/autowarm
  # idempotent: для обоих flag'ов
  sed -i '/^TT_MUSIC_RIGHTS_FALLBACK_ENABLED=/d' .env
  echo "TT_MUSIC_RIGHTS_FALLBACK_ENABLED=false" >> .env
  sed -i '/^TT_DUMP_POST_MUSIC_RIGHTS_XML=/d' .env
  echo "TT_DUMP_POST_MUSIC_RIGHTS_XML=false" >> .env
  pm2 restart autowarm --update-env
  ```
  Также disable SEED flag если был активирован:
  ```bash
  sed -i '/^TT_SEED_HARDENING_SAASCENE_ENABLED=/d' .env
  echo "TT_SEED_HARDENING_SAASCENE_ENABLED=false" >> .env
  pm2 restart autowarm --update-env
  ```
  **Note:** v10 — все три изменения flag-gated, full rollback через `.env` без `git revert`.
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
3. **MAX_MUSIC_RIGHTS_ITERATIONS interaction** — закрыт через RC-B.2 (reset `_music_rights_iter = 0` после `handled=True`).
4. **Backlog для следующего раунда (post-evidence):** после ≥5 dumps собрано — design RC-B detection extension. Кандидаты подходов: (a) lower nav-groups threshold в music-rights context, (b) supplemental positive-path detector с активити whitelist, (c) extend TT_MAIN_NAV_LABEL_GROUPS новыми observed строками.
