# YT cross-project leak — defense port from IG — design spec v1

**Date:** 2026-05-12
**Status:** Draft (awaiting Codex review)
**Related:** IG PR #36 (`f518a3f` Layer A+B+C+D, shipped 2026-05-12 11:48 UTC), prod commit `ada8076` changelog.

## Problem

После shipping IG cross-project leak defense (PR #36) выяснилось, что **тот же класс уязвимости существует в YouTube publisher** (`publisher_youtube.py`). На устройствах, где несколько проектов делят `/sdcard/Download/` (manual workflow менеджеров на phone #156-style multi-tenant rigs), YT picker может показать **чужой видеофайл** первым в галерее, и publisher слепо тапнет его → silent published wrong content (под нашим аккаунтом, но с чужим медиа).

В отличие от IG (где симптом — multi-clip склейка в одном Reels), в YouTube **симптом тише**: один файл публикуется как Short, никакой склейки не происходит, и telemetry показывает `done` с post_url. Обнаруживается только manual content audit.

## Evidence

### Vulnerability map — `publisher_youtube.py:1298–1346`

1. **Line 1326:** `items = video_items or all_items` — если video-filter (по подстрокам `видео|video|mp4|шорт|short|<fname>` в content-desc) не дал hit'ов, fallback на **ВСЕ кликабельные** items 200<cy<2000. Это включает кнопки, иконки, чужие медиа. Затем `content_items[0]` тапается слепо.

2. **Line 1344–1345:** `if not video_selected: ... self.adb_tap(181, 600)` — после 4 неудачных parse-попыток выполняется blind tap по фиксированным координатам. На multi-tenant device это всегда тапает первую плитку галереи, которая может принадлежать любому проекту.

3. **Нет pre-tap verify** — ни date check, ни MediaStore re-check. Push timestamp / expected basename доступны через `self._last_push_ts` и `self._last_expected_basename` (set в `publisher_base.py:3419–3420` после strict MediaStore validation), но не используются.

4. **Нет debug dump** перед tap'ом → пост-mortem reconstruction невозможен.

### Reference defense (IG, after PR #36)

`publisher_instagram.py:1662–1714` + helper `_layer_a_pre_tap_verify_ok` (line 261–337):

- **Layer A check 1 — date stamp:** parse thumbnail content-desc (`создано 12 мая 2026 г. 14:51` format) через `_ig_parse_thumbnail_date` (module-level, line 127); compare с `self._last_push_ts` ± 60s; abort с `ig_picker_wrong_candidate, reason=date_mismatch`.
- **Layer A check 2 — MediaStore re-check:** `self._ms_query('content://media/external/video/media')` top-1 `_display_name` должен совпасть с `self._last_expected_basename` (e.g. `autowarm_pq_1783_…`); abort с `ig_picker_wrong_candidate, reason=mediastore_top_mismatch`.
- Оба check'а **soft-fail** когда ground truth отсутствует — не блокируют публикации легитимные.
- **Удалены blind fallbacks** (RC-8 D2/D3): `all_clickable[0]` фолбэк и `(540, 721)` blind tap заменены на `ig_gallery_no_video_candidate` fail-fast.
- **Layer C debug dump** `ig_picker_pre_tap` перед каждым tap'ом.

### Why YT is identical in shape

| | IG | YT |
|---|---|---|
| Source | `/sdcard/Download/` + DCIM | то же |
| Picker UI | System gallery / IG inline picker | YouTube Shorts inline picker |
| Filter | `'видео'/'video' in d` | `'видео'/'video'/'mp4'/'шорт'/'short'/<fname>` |
| Fallback на all | ❌ (RC-8 D2 убран) | ✅ `items = video_items or all_items` |
| Blind coord fallback | ❌ (RC-8 D2/D3 убран) | ✅ `(181, 600)` |
| Pre-tap verify | ✅ Layer A | ❌ |
| Pre-tap dump | ✅ Layer C | ❌ |
| Multi-clip защита | ✅ Layer D | n/a (YT Short = 1 video) |

### Past leak detection — гарантировать невозможно

YT post-publish telemetry хранит `post_url` (YouTube Shorts URL) + наш upload basename, но **не сравнивает их** с тем что фактически на странице. Retro-проверка требует scraping Shorts pages (для всех YouTube успешных публикаций за период) — out of scope этой spec. Защита forward-only; existing leaked content не обнаружится этим фиксом.

## Goals

1. **Закрыть cross-project leak в YT picker** до tap'а — Layer A equivalents (date + MediaStore re-check), soft-fail на отсутствие ground truth, hard-fail на mismatch.
2. **Удалить blind paths** — `items = video_items or all_items` и `(181, 600)` blind tap. Заменить на `yt_gallery_no_video_candidate` fail-fast с диагностическим logging (mirror IG RC-8 D2).
3. **Добавить Layer C debug dump** `yt_picker_pre_tap` перед adb_tap.
4. **Reuse IG helpers** через вынесение в `publisher_helpers.py` shared module, чтобы избежать drift (single source of truth для date parser + Layer A logic).

## Non-goals

- Retro-detection past YT leaks — out of scope (см. выше).
- Менять IG публикацию — она уже защищена PR #36.
- Менять TT публикацию — у TT нет gallery picker такого формата (TT uses в-app camera/gallery flow, evidence не показывает leak).
- Менять gmail-coverage / `yt_target_not_in_picker` flow — отдельная работа (Шаг C).
- Multi-clip защита в YT — YT Shorts по UI единичный, multi-video upload отдельным flow и не используется autowarm scope.

## Approach

**Approach A (выбран): port + extract to shared helpers**

1. Вынести из `publisher_instagram.py` в `publisher_helpers.py`:
   - `_ig_parse_thumbnail_date` → `_parse_picker_thumbnail_date` (generic, без IG prefix; signature unchanged)
   - `_ig_thumbnail_date_re` / `_russian_months` / `_msk` constants → public symbols в helpers
2. Сделать `_layer_a_pre_tap_verify_ok` методом, который доступен и в `PublisherInstagram` и в `PublisherYoutube` — два варианта:
   - **A.1:** mixin `_CrossProjectLeakDefenseMixin` в helpers с методом → IG/YT наследуются от него
   - **A.2:** standalone function `layer_a_pre_tap_verify(publisher_self, candidate_desc, *, event_category) -> bool` в helpers, вызывается из обоих publishers
3. Patch `publisher_instagram.py:1673` чтобы вызывать новую shared logic (regression check — должно остаться identical behaviour, тот же event_category=`ig_picker_wrong_candidate`).
4. Patch `publisher_youtube.py`:
   - перед `self.adb_tap(cx, cy)` на line 1336 — вставить Layer A verify (event_category=`yt_picker_wrong_candidate`)
   - перед line 1336 — добавить Layer C dump `yt_picker_pre_tap`
   - удалить `items = video_items or all_items` (line 1326) → `items = video_items` only
   - если `video_items` пуст за все 4 parse_attempt — fail-fast `yt_gallery_no_video_candidate` (mirror IG RC-8 D2)
   - удалить blind `(181, 600)` fallback (line 1344-1345) — fail-fast тот же
   - в meta включить `all_clickable_count` + `first_clickables: [{cx, cy, desc[:120]}]` (mirror IG diagnostic)

**Approach B (rejected):** duplicate code IG → YT без extraction. Drift гарантирован.

**Approach C (rejected):** только удалить blind paths без Layer A port. Сэкономит код, но не закроет случай когда video_items дал hit на чужое видео (если у другого проекта в content-desc тоже есть слово «видео»).

Выбран Approach A потому что **(a)** strictly better safety на multi-tenant rigs, **(b)** unified codebase для future Layer A enhancements (e.g. file-size verify), **(c)** один codex review pass на shared logic vs два независимых.

## Implementation outline

```
publisher_helpers.py:
  + RUSSIAN_MONTHS, MSK, THUMBNAIL_DATE_RE (raised from IG module-level)
  + parse_picker_thumbnail_date(desc) -> Optional[datetime]
  + layer_a_pre_tap_verify(publisher_self, candidate_desc, *,
                            event_category, artifact_prefix) -> bool
        # Same 2-check logic as _layer_a_pre_tap_verify_ok in IG
        # event_category вариирует ig_picker_wrong_candidate / yt_picker_wrong_candidate

publisher_instagram.py:
  - def _ig_parse_thumbnail_date(...)
  + from publisher_helpers import parse_picker_thumbnail_date
  - def _layer_a_pre_tap_verify_ok(self, ...): <full body>
  + def _layer_a_pre_tap_verify_ok(self, d): return layer_a_pre_tap_verify(self, d,
        event_category='ig_picker_wrong_candidate',
        artifact_prefix='ig_picker_wrong_candidate')
  # call site (line 1673) — unchanged

publisher_youtube.py:
  + from publisher_helpers import layer_a_pre_tap_verify
  + before self.adb_tap(cx, cy):     # line 1336
        if not layer_a_pre_tap_verify(self, d,
                event_category='yt_picker_wrong_candidate',
                artifact_prefix='yt_picker_wrong_candidate'):
            return False
        try: self._save_debug_artifacts('yt_picker_pre_tap')
        except Exception: pass
  - items = video_items or all_items
  + items = video_items
  - if not video_selected:
  -     log.warning('  Fallback видео: тапаем (181,600)')
  -     self.adb_tap(181, 600); time.sleep(4)
  + if not video_selected:
  +     log.error('Видео не найдено в YT gallery picker — abort')
  +     self._save_debug_artifacts('yt_gallery_no_video')
  +     diag = [{'cx': i[4], 'cy': i[5], 'desc': i[6][:120]}
  +             for i in all_items[:10]]
  +     self.log_event('error',
  +         'YT: видео не найдено в gallery picker — fail-fast',
  +         meta={'category': 'yt_gallery_no_video_candidate',
  +               'platform': self.platform, 'step': 'yt_gallery_select',
  +               'all_clickable_count': len(all_items),
  +               'first_clickables': diag})
  +     return False
```

## Test plan

### Unit tests (publisher_helpers)

1. `test_parse_picker_thumbnail_date_ru_with_nbsp` — IG-style desc `'… создано 12 мая 2026\xa0г. 14:51'` → datetime(2026, 5, 12, 14, 51, tzinfo=MSK).
2. `test_parse_picker_thumbnail_date_ru_with_space` — fallback на обычный пробел.
3. `test_parse_picker_thumbnail_date_unparseable` → None (no exception).
4. `test_parse_picker_thumbnail_date_none_input` → None.
5. **TBD** — `test_parse_picker_thumbnail_date_yt_format` — если YT thumbnail format отличается (исследовать на live device, добавить regex). Если совпадает — этот тест избыточен.
6. `test_layer_a_date_match_within_60s` — push_ts = 14:51:00, thumb = 14:51:30 → True (within tolerance).
7. `test_layer_a_date_mismatch_2min` — push_ts = 14:51, thumb = 14:53:30 → False + event logged.
8. `test_layer_a_mediastore_top_match` — _ms_query returns expected → True.
9. `test_layer_a_mediastore_top_mismatch` — _ms_query returns foreign filename → False + event logged.
10. `test_layer_a_softfail_no_push_ts` — `_last_push_ts=None` → True (skip date check).
11. `test_layer_a_softfail_no_expected_basename` — `_last_expected_basename=None` → True (skip MediaStore check).
12. `test_layer_a_event_category_ig_vs_yt` — same logic, different event_category в logged meta.

### Integration (publisher_instagram) — regression guard

13. `test_ig_layer_a_call_site_unchanged_after_refactor` — патч сохраняет точку вызова и event_category=`ig_picker_wrong_candidate`. Smoke: один существующий IG-test (pkr test) после refactor должен пройти без изменений.

### Integration (publisher_youtube) — new

14. `test_yt_picker_no_video_candidates_fails_fast` — `dump_ui` возвращает gallery без `'видео'` в desc → `yt_gallery_no_video_candidate` event + return False, **никакого** adb_tap не выполнено.
15. `test_yt_picker_layer_a_date_mismatch_aborts` — fixture XML с одним video_candidate, dt=14:55, push_ts=14:51 (delta 4min) → abort с `yt_picker_wrong_candidate, reason=date_mismatch`.
16. `test_yt_picker_layer_a_mediastore_mismatch_aborts` — _ms_query mock returns foreign basename → abort.
17. `test_yt_picker_layer_a_pass_taps_video` — все check'и pass → adb_tap(cx, cy) выполнен + `yt_picker_pre_tap` artifact saved.
18. `test_yt_picker_no_blind_181_600_fallback` — assert что в коде после изменения нет `adb_tap(181, 600)`.

### Live verify (post-deploy)

19. Phone #19 (или другой YT testbench), один аккаунт с phone, который хостит несколько проектов:
   - **Positive:** обычный publish → pass Layer A, see `yt_picker_pre_tap` artifact, post_url returned.
   - **Negative (induced):** push наш видео, manually закинуть в `/sdcard/Download/` foreign mp4 с MediaStore date > нашего push_ts на 5 минут (через `cp + touch`), trigger publish → должен abort с `yt_picker_wrong_candidate`.
20. 24h soak post-deploy — мониторить `yt_picker_wrong_candidate` event count + `yt_gallery_no_video_candidate` event count.

## Rollout / kill-switch

- **Single PR** в prod-репо ветка `feat-yt-cross-project-leak-fix-20260512`.
- **No feature flag** — это bug-fix как и IG PR #36. Логика soft-fail (`getattr(self, '_last_push_ts', None) is None` → skip check) сама работает как kill-switch: если `publisher_base` push-tracking ломается, fix degrades to pre-fix behaviour (минус blind fallback, но это правильно).
- **Rollback:** `git revert <commit>` + auto-push hook прокатает. Без миграций.
- **Mid-flight kill:** SQL-flag не нужен; если нужно срочно отключить Layer A — set **обе** ground-truth ссылки в base: `_last_push_ts=None` AND `_last_expected_basename=None`. Очистка только одной поднимет only одну check'у в soft-fail, вторая продолжит abort'ить (Codex round 1 P2). Fail-fast на удалённых blind paths остаётся в любом случае — это правильно (cross-project leak severity > extra fails).

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| YT thumbnail format ≠ IG → date parse всегда None → Layer A check 1 всегда soft-fail | Medium | MediaStore check 2 — primary defense; работает независимо от parse'а. Если нужно — добавить YT-specific regex в helpers позже (separate PR). |
| Удаление `(181, 600)` blind tap → больше fail-fast'ов на устройствах где legitimately нет видео | Low-Med | Это **правильное** поведение — публиковать чужое нельзя. Но мониторить `yt_gallery_no_video_candidate` rate; если >5/24h — discover root cause (device state, не код). |
| Refactor IG `_layer_a_pre_tap_verify_ok` → shared может сломать IG | Low | Test 13 (regression guard) + 1 existing IG path remains call site identical. Smoke на phone #19 IG-publish после deploy. |
| MediaStore top-1 ≠ ground truth когда наш push не первый в storage (другой проект push'ит ровно после нашего) | Low | `_last_push_ts` set после **strict** MediaStore validation (publisher_base.py:3419). Если race случился — это сама cross-project ситуация которую защищаем; abort правильный. |
| YT picker может показать gallery в другом порядке (НЕ MediaStore top-1) | Low-Med | Если такое — Check 2 будет false-positive abort. Soft-fail при отсутствии expected_basename — нет; abort hard. Mitigation: monitor 24h post-deploy. Если соберём evidence — добавить feature flag `YT_LAYER_A_MS_CHECK_ENABLED`. |

## Open questions for Codex

1. Сделать `layer_a_pre_tap_verify` standalone function (Approach A.2) или mixin (A.1)? Я склоняюсь к standalone — меньше связности.
2. event_category naming: `yt_picker_wrong_candidate` зеркалит `ig_picker_wrong_candidate`. OK?
3. artifact prefix naming: `yt_picker_wrong_candidate_date` / `yt_picker_wrong_mediastore_top`? Зеркалит IG.
4. Должны ли мы fail-fast на blind fallback **уже сейчас**, или дать одну транзитную версию с warning-only (log without abort) для baseline? Я склоняюсь к immediate fail-fast (вред от cross-project leak severity выше чем от extra fails).
5. `_save_debug_artifacts` exception swallow — IG делает `try/except Exception: pass`. Зеркалить.
