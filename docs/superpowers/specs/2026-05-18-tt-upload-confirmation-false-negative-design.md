# TT publish: false-negative `tt_upload_confirmation_timeout` — design

**Дата:** 2026-05-18
**OpenProject:** [WP #82](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/82)
**Файлы:** `publisher_tiktok.py` (один файл, изменения в `_wait_upload_confirmation` + `_tt_infer_post_publish_success` + перм-detector + новый promo-handler)

---

## Проблема

10 из 14 TT-фейлов сегодня (2026-05-18) падают с `tt_upload_confirmation_timeout` несмотря на то, что **видео фактически опубликовано**. UI-дамп iter1 для task 6750 показывает экран профиля с карточкой `tkachenko_biohacking · 1 с. назад` + кнопкой `Get more views` — пост уже в ленте, а наш `_wait_upload_confirmation` ещё 5 минут ждёт и убивается watchdog'ом.

Эффект: false-failed таски → re-queue → потенциальные дубли в TT, искажённая статистика, лишний шум в триаже.

## Корневые причины (4 связанных бага)

Все четыре проявляются в одном loop'е `_wait_upload_confirmation` (`publisher_tiktok.py:1820+`):

1. **`_tt_infer_post_publish_success` стоит слишком поздно** (line 2164). Перед ним — retap-ветка (line 2086-2142), generic dialog handler (line 2152), которые перехватывают управление и `continue`'ят, не давая детектору шанса.

2. **`share_btn_clickable` substring-match — false-positive** (line 2094):
   ```python
   if 'поделиться' in txt or txt.strip() == 'post':
   ```
   На профиле после публикации overlay содержит content-desc `«Поделиться видео. Уже поделились:»` — substring 'поделиться' хватает. Бот думает что мы ещё на editor → retap. 6750/6788/6814 цикл.

3. **FB-friends perm-dialog не matchится existing detector'ом.** `_TT_PERM_DIALOG_TITLE_SUBSTRING = 'доступ к контактам'`, а dialog 6789/6809 показывает `«доступ к списку ваших друзей в Facebook»`. Проваливается в generic handler, который жмёт OK, dialog re-presentится, success-check не запускается.

4. **Promo-модал «Улучшенные входящие сообщения для бизнеса»** (6750-iter10+, 6804). Generic handler жмёт «Закрыть» (clickable=true), но TT мгновенно re-presentит модал. Loop до watchdog. Никакого специфичного handler'а нет.

5. **Bonus — нет cap'а:** существующий perm-dialog handler (6792) дисмиссит 25+ раз подряд, publish уже произошёл, но handler не знает что пора сдаться и признать success.

## Распределение TT-фейлов за 2026-05-18 (UTC)

| error_code | cnt |
|---|---|
| `tt_upload_confirmation_timeout` | **10** |
| `tt_profile_tab_broken` | 3 |
| `tt_post_switch_verify_unrecoverable` | 1 |

Эта спека закрывает топ-категорию полностью (все 10 кейсов).

## Дизайн фикса

### Принцип
Post-publish детектор `_tt_infer_post_publish_success` запускается **первым** в каждой итерации `_wait_upload_confirmation`, ДО всех retap/dialog/handler веток. Детектор расширяется так, чтобы работать и когда диалог перекрывает bottom-nav. Specific dialog handlers с cap → success.

### Change 1 — продвинуть success-check в начало wait-loop

**Где:** `publisher_tiktok.py:1820+`, внутри `for wait in range(...)` сразу после `ui = self.dump_ui()`.

**Что:** новый блок (под env-flag `TT_POSTPUBLISH_EARLY_CHECK_ENABLED`, default `true`):
```python
cur_act_early = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"', timeout=8) or ''
success_early, meta_early = _tt_infer_post_publish_success(ui, cur_act_early, wait)
if success_early:
    self.log_event('info',
        f'TikTok: post-publish success (early) — {meta_early["reason"]}',
        meta={'category': 'tt_post_publish_success_inferred',
              'platform': self.platform, 'wait_iteration': wait,
              'detector_position': 'early', **meta_early})
    upload_confirmed = True
    break
```

**Старый success-check блок на line 2160-2179 НЕ удаляется.** Гейтится за обратным условием:
- `TT_POSTPUBLISH_EARLY_CHECK_ENABLED=true` (default) → выполняется только early-блок, поздний `if False:` skip;
- `=false` → early-блок skip, поздний выполняется как раньше (полный rollback).

Таким образом ровно один из двух блоков активен в итерации.

### Change 2 — расширить `_tt_infer_post_publish_success` тремя XML-маркерами

**Где:** `publisher_tiktok.py:85-162`.

**Что:** после существующих веток (DetailActivity / composer_seed / nav-groups) — новый блок маркеров (под env-flag `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED`, default `true`):

| Маркер | Regex/match | reason |
|---|---|---|
| Кнопка «Get more views» | XML node `class=android.widget.Button` AND `text="Get more views"` | `fresh_post_cta` |
| Timestamp свежего поста | regex `· \d+ с\. назад` ИЛИ `· \d+ s ago` ИЛИ `· \d+ мин\. назад` в XML | `fresh_post_timestamp` |

**Defensive bonus:** если `on_tiktok=False` (пустой dumpsys), но XML-маркеры выше — success всё равно True. Защита от flaky adb dumpsys. Логируется `reason=fresh_post_marker_no_activity`.

`meta` обогащается: `markers_matched: ["fresh_post_cta", ...]`.

### Change 3 — tighten `share_btn_clickable` (exact-match)

**Где:** `publisher_tiktok.py:2088-2099` (XML scan для определения «мы ещё на editor»).

**Что:**
```python
# OLD: if 'поделиться' in txt or txt.strip() == 'post':
if (txt.strip() in ('Поделиться', 'Post', 'Publish')
    or desc.strip() in ('Поделиться', 'Post', 'Publish')):
    share_btn_clickable = True
```

`«Поделиться видео. Уже поделились:»` больше не false-positive. Без env-flag (локальный багфикс, ничтожный риск регрессии — exact match реальной share-кнопки сохраняется).

### Change 4 — perm-dialog + promo-modal handlers с cap → success

**4(a)** Расширить `_TT_PERM_DIALOG_TITLE_SUBSTRING` на список:
```python
_TT_PERM_DIALOG_TITLE_SUBSTRINGS = [
    'доступ к контактам',                       # existing
    'доступ к списку ваших друзей в Facebook',  # NEW (6789, 6809)
]
```
`_detect_tt_contacts_perm` пробегает по списку (any). Без env-flag.

**4(b)** Новый handler `_handle_tt_promo_inbox_modal` (parallel к existing `_handle_samsung_stories_overlay`):
- Detector: substring `«Улучшенные входящие сообщения для бизнеса»` в UI.
- Strategy: tap content-desc=`Закрыть` (clickable, bounds.y < screen_h*0.3) → KEYCODE_BACK → fail-and-cap.
- Cap: `MAX_TT_PROMO_INBOX_ITERATIONS = 5`. После 5 неудачных dismiss + redetect: log `tt_post_publish_inferred_from_promo_loop` + `upload_confirmed = True; break` (caller wait_upload).
- Env-flag: `TT_PROMO_INBOX_MODAL_HANDLER_ENABLED`, default `true`.

**4(c)** В existing `_handle_tt_contacts_perm` (line 512+): после `MAX_TT_PERM_DIALOG_ITERATIONS = 5` (новая константа) повторных dismiss без выхода из dialog'а — log `tt_post_publish_inferred_from_perm_loop` + возврат tri-state `'inferred_success'` (вместо `True`/`False`).

Caller (`publisher_tiktok.py:1980-1984`) обновляется на tri-state:
```python
if self._detect_tt_contacts_perm(ui):
    res = self._handle_tt_contacts_perm(ui, wait)
    if res == 'inferred_success':
        upload_confirmed = True
        break
    if not res:
        return False
    time.sleep(1.5); continue
```

`_handle_tt_promo_inbox_modal` использует тот же контракт (tri-state). Existing handlers Samsung overlay / in-app stories — без изменений (там нет cap-success сценария).

**Cap-rationale:** оба модала (promo-inbox и FB-friends perm) появляются в TT только ПОСЛЕ успешной публикации (онбординг-промо для свежего поста / perm-prompt после первого post в сессии). Если зациклились — publish произошёл. Cap=5 покрывает transient race conditions, отделяет от реального loop'а.

## Тесты

В `tests/test_publisher_tt_overlay_handlers.py`:

1. **`test_infer_success_fresh_post_cta`** — UI с `Get more views` Button + empty top_activity → success=True, reason=`fresh_post_cta`.
2. **`test_infer_success_fresh_post_timestamp`** — UI с `· 1 с. назад` → success=True, reason=`fresh_post_timestamp`.
3. **`test_share_btn_clickable_no_false_positive_on_overlay`** — UI с content-desc `Поделиться видео. Уже поделились:` → share_btn_clickable=False.
4. **`test_perm_dialog_fb_friends_detected`** — UI с `доступ к списку ваших друзей в Facebook` → `_detect_tt_contacts_perm`=True.
5. **`test_promo_inbox_modal_detected_and_capped`** — UI с «Улучшенные входящие сообщения для бизнеса» → handler detect=True; на 6-й итерации без выхода → `upload_confirmed=True` сигнал.
6. **`test_perm_dialog_cap_breaks_with_success`** — perm-dialog не выходит из loop'а 5+ iter → `_handle_tt_contacts_perm` возвращает `'inferred_success'`.

**Fixtures:** реальные XML-дампы из инцидента копируются в `tests/fixtures/tt_post_publish/`:
- `task6750_iter1_profile_with_fresh_post.xml` (60KB)
- `task6750_iter10_promo_inbox_modal.xml` (12KB)
- `task6789_iter1_fb_friends_perm.xml` (5KB)

## Env-flags (kill-switches)

Все 3 «новых» изменения за флагами с default `true`. Pattern — как у `TT_SAMSUNG_OVERLAY_HANDLER_ENABLED`:

| Flag | Что отключает | Default |
|---|---|---|
| `TT_POSTPUBLISH_EARLY_CHECK_ENABLED` | Change 1 (продвижение детектора) | `true` |
| `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED` | Change 2 (новые маркеры) | `true` |
| `TT_PROMO_INBOX_MODAL_HANDLER_ENABLED` | Change 4(b) (новый promo-handler + cap) | `true` |

Change 3 (substring → exact) и Change 4(a) (FB-friends в perm SUBSTRING) — без флагов: локальные багфиксы, риск ничтожный.

## Observability — новые events

| Event category | Когда | Зачем |
|---|---|---|
| `tt_post_publish_success_inferred` (с `detector_position: 'early'/'late'`) | success через основной детектор | разделение «новый путь» от старого через meta |
| `tt_post_publish_inferred_fresh_post` (через `markers_matched`) | success через новые XML-маркеры | observability нового пути |
| `tt_post_publish_inferred_from_promo_loop` | promo-modal cap → success | SQL-grep для health-check; signal что cap-логика стрельнула |
| `tt_post_publish_inferred_from_perm_loop` | perm-dialog cap → success | same, для perm-dialog |
| `tt_promo_inbox_modal_detected` | первое появление модала за task | tracking новой проблемы TT |
| `tt_promo_inbox_modal_dismissed` | успешный dismiss до cap | счёт успехов handler'а |

## 24h success metrics (после deploy)

```sql
-- Должен упасть с ~10/день к ≤2/день
SELECT COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND status='failed'
  AND error_code='tt_upload_confirmation_timeout'
  AND created_at >= NOW() - INTERVAL '24 hours';

-- Должен быть > 0 (proof что новые пути работают)
SELECT COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND created_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_post_publish_inferred_fresh_post"}}]';

-- Cap-логика
SELECT COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND created_at >= NOW() - INTERVAL '24 hours'
  AND (events @> '[{"meta":{"category":"tt_post_publish_inferred_from_promo_loop"}}]'
    OR events @> '[{"meta":{"category":"tt_post_publish_inferred_from_perm_loop"}}]');
```

## Risk-breakdown

| Риск | Митигация |
|---|---|
| Cap → false success на действительно сломанной публикации | Cap=5, не 1-2; новые `tt_post_publish_inferred_from_*` events дают operator'у grep для post-mortem; rollback через env-flag |
| Новые маркеры false-positive на не-post экране | Маркеры требуют `Get more views` Button (exact class+text) ИЛИ `· N с. назад` regex — оба специфичны для TT post-publish UI |
| Промотированный success-check блокирует валидные retap-сценарии | Сценарии где мы РЕАЛЬНО ещё на editor — не имеют ни DetailActivity, ни bottom-nav, ни fresh-post маркеров → детектор вернёт False, retap идёт как раньше |
| Перехват editor'а с timestamp от чужого поста в ленте под composer'ом | composer_seed-проверка возвращает False ДО timestamp-маркера; на real editor нет ленты в фоне |

## Out of scope

- `tt_profile_tab_broken` (3/14) — отдельная корневая причина, другой WP.
- `tt_post_switch_verify_unrecoverable` (1/14) — closed by [[project_tt_switcher_bool_return_fixed]] неделю назад, residual.
- Само наличие promo-модала «Улучшенные входящие» — мы его не убираем из TT, только перестаём на нём зацикливаться. Если он начнёт появляться часто — отдельная задача (возможно env-flag для отключения новых TT-фич через настройки приложения).

## Связанные spec'и

- `2026-05-11-tt-post-publish-success-detection-design.md` — origin `_tt_infer_post_publish_success`
- `2026-05-12-tt-wait-upload-overlay-handlers-design.md` — origin overlay handlers framework (Samsung / in-app stories / contacts perm)
- `2026-05-11-tt-music-rights-coverage-and-post-accept-design.md` — `_maybe_dump_post_music_rights_xml` infrastructure
