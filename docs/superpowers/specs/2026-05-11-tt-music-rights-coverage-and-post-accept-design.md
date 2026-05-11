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
- **RC-A coverage:** Доля task'ов с `tt_music_rights_accepted=true` среди failed RC-A-cases должна вырасти. Считаем `tt_music_rights_fallback_match` events за 24h — каждый event = ранее упускавшийся matcher case теперь покрыт. Целевое: **≥3 events за первые 24h** (calibration); если 0 за 24h — fallback слишком строгий ИЛИ TT уже стабилизировал title text.
- **RC-A false-positives:** 0 events `tt_music_rights_button_changed_suspect` followed by downstream `publish_failed_generic` с UI XML show no actual music-rights dialog. (Manual review evidence-only XML's за 24h.)
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

Два feature-flag'а:

| Flag | Default | Покрытие |
|---|---|---|
| `TT_MUSIC_RIGHTS_FALLBACK_ENABLED` | `false` | RC-A: fallback matcher + dump XML на fallback-match |
| `TT_DUMP_POST_MUSIC_RIGHTS_XML` | `false` | RC-B.4: per-iteration XML dump после accept (инструментация, opt-in) |

При **всех** flag=false поведение идентично текущему prod (PR #28 + PR #29).

**Что НЕ за feature flag** (всегда on — narrow targeted bug fixes):
- **`SAASceneWrapperActivity` добавлен в `TT_COMPOSER_ACTIVITIES_SEED`** — закрывает known hole в существующем detector'е (memory `reference_tt_activities_observed`). Не за flag'ом потому что: (a) уже зафиксированный composer activity в проде, (b) включение в SEED делает detector БОЛЕЕ строгим (anti-false-positive direction; не может ввести новых false-positives).

### Точки изменений

| # | Где | Что |
|---|---|---|
| **RC-A.1** | `_detect_tt_music_rights_dialog` (стр. 209-257) | Новый метод `_detect_tt_music_rights_dialog_fallback(ui_xml) -> bool` |
| **RC-A.1b** | Same area | Новый метод `_detect_tt_music_rights_dialog_evidence_only(ui_xml) -> bool` — evidence-only path |
| **RC-A.2** | `_handle_tt_music_rights_dialog` (стр. 347-389) | Hybrid invoke: strict → fallback → evidence-only |
| **RC-B.0 (always-on)** | `TT_COMPOSER_ACTIVITIES_SEED` (стр. 53-62) | Добавить `'SAASceneWrapperActivity'` в tuple — fixes known SEED hole (memory `reference_tt_activities_observed`) |
| **RC-B.1** | `publish_tiktok` (стр. 391+) | Сброс `_music_rights_just_accepted_iter = None`, `_music_rights_accepted_ts = None` в начале (рядом с `_music_rights_iter = 0`) |
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
       c) (a) и (b) находятся **в общем dialog-контейнере**. Codex round 4,
          P2#4: bounds-overlap ±200px фрагилен на больших экранах (TT-диалог
          может растягиваться вертикально). Используем ancestry-based check:
          подняться по родителям от node-(a) и от node-(b), найти общий
          ancestor; ancestor должен иметь class содержащий 'Dialog' OR
          'PopupWindow' OR 'AlertDialog' OR быть `FrameLayout`/
          `LinearLayout`/`RelativeLayout` с package = TT-package
          (`com.zhiliaoapp.musically` или `com.ss.android.ugc.trill`).
          Если общий ancestor не найден за 8 уровней — fallback fails.

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

Возвращает `True` ⟺ lowercase substring найден AND checkbox-label EXACT AND clickable button EXACT AND bounds overlap. Иначе `False`. (Codex round 2, P1#1 + round 3, P2#1: legacy формула `specific structure OR generic checkbox` устранена.)

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

### RC-B.0: Always-on SEED hardening

Расширение существующей константы (стр. 53-62):

```python
TT_COMPOSER_ACTIVITIES_SEED = (
    'PostActivity',
    'EditActivity',
    'PublishActivity',
    'CameraActivity',
    'PermissionActivity',
    'MusicSelectActivity',
    'CutVideoActivity',
    'CoverActivity',
    'SAASceneWrapperActivity',  # v6 added: composer wrapper, NOT in original SEED
)
```

**Rationale:** memory `reference_tt_activities_observed` зафиксирована наблюдаемая activity, но в SEED не попала. Это закрывает known hole: PR #29 detector мог посчитать `SAASceneWrapperActivity` как «non-composer» state и затем bottom-nav fallback мог дать false-positive если nav-labels случайно matchились.

Без feature flag — narrow targeted fix. Direction of change: detector становится БОЛЕЕ строгим (anti-false-positive), не более permissive.

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
| `test_detect_fallback_no_common_dialog_ancestor` | XML с substring + checkbox-label + button EXACT, но nodes под разными root-children (нет общего Dialog/Layout ancestor за 8 уровней) | fallback returns False (Codex round 4, P2#4: ancestry-based single-dialog check) |
| `test_detect_fallback_with_common_layout_ancestor` | XML где checkbox + button под общим `LinearLayout` (TT package) на 3 уровне выше — далеко по Y | fallback returns True (Codex round 4, P2#4: ancestry заменил fragile bounds-overlap) |
| `test_detect_fallback_no_substring` | XML без указанных substring'ов | fallback returns False |
| `test_evidence_only_substring_no_button_triggers_dump` | XML с substring 'music rights' + generic checkbox, без EXACT button | `_detect_evidence_only` returns True; handler dump'ит XML с suffix `button_changed_suspect`; возвращает False |
| `test_strict_still_primary` | EXACT title XML | strict returns True; fallback не вызывается |
| `test_handle_with_fallback_writes_dump` | mock fallback match + `tmp_path` для dump | XML файл создаётся; log_event с `matched_via='fallback'`; filename содержит timestamp |
| `test_handle_creates_dump_dir_if_missing` | удалить `/tmp/autowarm_ui_dumps/` перед вызовом + mock fallback match | dump-файл создан, директория создана автоматически (Codex round 1, P2#7) |
| `test_seed_includes_saascenewrapperactivity` | parse TT_COMPOSER_ACTIVITIES_SEED | `'SAASceneWrapperActivity' in TT_COMPOSER_ACTIVITIES_SEED` (RC-B.0 always-on) |
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
2. Запустить 2-3 re-queue для одного из недавних RC-A failed task'ов (4536) — проверить fallback fires; XML dump сохранён.
3. Запустить re-queue для RC-B failed task (4542) — проверить activity-check fires если publish реально прошёл.

Если testbench недоступен / Pi 9 orphan не resolved — деплой сразу в prod за flag'ом `false`, активация через `pm2 set` после smoke на следующий же publish с music-rights detected треком.

### Прод-rollout

**Активация env-vars — через `.env` файл + `pm2 restart --update-env`** (Codex round 2, P2#2: `pm2 set` устанавливает PM2-global, НЕ `os.environ` для процессов; код читает `os.environ`, поэтому нужно либо `.env` через ecosystem-config dotenv loader, либо явный `restart --update-env`).

Точные шаги:

1. Deploy кода с **тремя** flag'ами `false` (defaults). Smoke green (pytest pass).
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
4. Мониторинг 4-6 часов:
   - Считаем events: `tt_music_rights_fallback_match`, `tt_music_rights_button_changed_suspect`.
   - Через 24h: проверить, что RC-A покрытие выросло (`tt_music_rights_accepted=true` за period). Если уменьшилось `tt_upload_confirmation_timeout` где events НЕ содержат `tt_music_rights_accepted` (= RC-A победа), это валидация fix'а.
   - Через 24-48h: разобрать `/tmp/autowarm_ui_dumps/tt_post_music_rights_*.xml` для всех failed tasks с `mr_accept=true, pp_inferred=false`. Это input для следующего раунда RC-B spec'а.
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
   - Считаем false-positive: `tt_post_publish_success_inferred (в music_rights context)` но task потом завершилась как `publish_failed_*` или контент не появился в feed'е → false-positive.

### Если за 6 часов 0 успехов через post-music-rights detection и >=1 fallback-match XML сохранён

Exit rollout, читаем XML, итерируем дизайн на основе реальных данных (расширение activity list / UPLOAD_OK markers / button-text константы).

---

## Rollback

- Симметричный к rollout — через `.env` + `pm2 restart --update-env` (Codex round 3, P2#2: `pm2 set` не влияет на `os.environ`, а код читает оттуда). Для каждого flag'а:
  ```bash
  cd /root/.openclaw/workspace-genri/autowarm
  # idempotent toggle: if key exists, replace; if not, append
  sed -i '/^TT_MUSIC_RIGHTS_FALLBACK_ENABLED=/d' .env
  echo "TT_MUSIC_RIGHTS_FALLBACK_ENABLED=false" >> .env
  pm2 restart autowarm --update-env
  ```
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
4. **RC-B.3 placement: оба вызова `_tt_infer_post_publish_success`** (стр. 1092 + 1126) должны иметь streak-gate. Plan-stage: выделить общую helper-функцию `_tt_confirm_or_pend_with_streak(success, _meta, ui, wait)` чтобы не дублировать gate-логику.
