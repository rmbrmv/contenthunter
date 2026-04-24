# Publish Tasks — S3 upload скринов и XML-дампов

**Branch:** `feature/publish-tasks-s3-artifacts` (from `main`)
**Created:** 2026-04-24
**Plan type:** full
**Scope:** autowarm publisher — лог задач в UI `/publishing/publishing?sub=up:tasks`

## Settings

- **Testing:** yes (unit-tests на S3 upload helper, integration smoke)
- **Logging:** verbose (DEBUG перед upload'ом, INFO после success, WARNING на fallback)
- **Docs:** no

## Roadmap Linkage

Milestone: "none" — не привязан к roadmap-итерации, точечный UX-fix.

## Problem statement

На странице `https://delivery.contenthunter.ru/#publishing/publishing?sub=up%3Atasks` каждая задача публикации имеет лог (events). В логе рендерятся ссылки на артефакты:
- скрины (`meta.screenshots[]`) вида `/screenshots/publish_171_*.png`
- xml-дампы (`meta.ui_dumps[]`) вида `/ui_dumps/publish_171_*.xml`

Эти URL — относительные, резолвятся через express-static (`server.js:179-181`) на файлы в `/tmp/autowarm_screenshots/` и `/tmp/autowarm_ui_dumps/`. Файлы быстро исчезают (перезапуск VPS, cleanup /tmp), и ссылки становятся битыми. Скринкасты (.mp4) уже заливаются на S3 Beget (эндпоинт `https://s3.ru1.storage.beget.cloud`) и в UI работают стабильно.

**Цель:** скрины и xml-дампы заливать на тот же S3 по образцу screencast'ов, в `meta.screenshots[*]` / `meta.ui_dumps[*]` сохранять полные публичные URL.

## Evidence (код, место правки)

| Артефакт | Функция | Файл:строка | Текущий URL |
|---|---|---|---|
| Скринкаст (.mp4) — эталон | `stop_and_upload_screen_record` | publisher.py:~2415-2438 | `https://save.gengo.io/autowarm/screenrecords/...` ✅ |
| Скрин (.png) | `_save_debug_screenshot` | publisher.py:~1687-1714 | `/screenshots/...` ❌ |
| XML-дамп (.xml) | `_save_debug_ui_dump` | publisher.py:~1893-1917 | `/ui_dumps/...` ❌ |
| Emit ссылок | `_fail_task` → `log_event('fail', meta=...)` | publisher.py:~1612-1654 | meta.screenshots/ui_dumps |
| Backend API | `GET /api/publish/tasks/:id/events` | server.js:~1841-1850 | отдаёт events JSONB |
| Frontend render | `upShowEvents(taskId)` | public/index.html:~10718-10803 | `<a href="${u}">` |
| Static fallback | `express.static('/tmp/autowarm_*')` | server.js:~179-181 | легаси для старых задач |

**Продакшен-код:** `/root/.openclaw/workspace-genri/autowarm/` (pm2 `autowarm` на 3848 → delivery.contenthunter.ru). Зеркало: `/home/claude-user/autowarm-testbench/` (testbench pm2 на 3849 → tasks.contenthunter.ru). Файлы идентичны по размеру — auto-push git-hook (memory: `reference_autowarm_git_hook`) автоматически синкает prod в GenGo2/delivery-contenthunter.

## Архитектурные решения

1. **Общий helper** `upload_artifact_to_s3(local_path, platform, task_id, kind, content_type) → s3_url|None`. Не рефакторим пока screencast upload — просто выносим shared-логику для новых артефактов.
2. **Graceful fallback**: если S3 не ответил → возвращаем прежний `/screenshots/{fname}` и пишем WARNING. Задача публикации НЕ должна падать из-за проблем с upload'ом.
3. **Ключ S3**: `autowarm/<kind>s/<platform>/task{task_id}_{basename}` — mirror screencast layout (`autowarm/screenrecords/<platform>/...`).
4. **Content-Type** выставляем явно: `image/png`, `application/xml` — чтобы браузер открывал inline, а не скачивал.
5. **Локальные файлы в /tmp** удаляем после success upload'а (env var `AUTOWARM_S3_ARTIFACTS_KEEP_LOCAL` для debug override).
6. **БД-schema не меняем**: `publish_tasks.screenshot_url` (single) и JSONB `events[*].meta.{screenshots,ui_dumps}[]` уже принимают абсолютные URL — просто подсовываем S3 вместо `/screenshots/...`.
7. **Legacy static-routes** в `server.js` не удаляем — пусть живут как fallback для задач до deploy'а.

## Tasks

Блок-схема зависимостей:

```
T1 (helper) ─┬─> T2 (screenshot) ──┐
             ├─> T3 (ui_dump)   ───┤
             └─> T5 (unit tests) ──┼─> T6 (smoke) ─> T9 (prod deploy)
                                   │       │
                                   │       └─> T8 (cleanup) ───┘
                                   └─> T4 (bucket policy) ─────┘
                                                               T7 (legacy UI hint)
```

### Phase 1: Scaffold helper

- [x] **T1 — Вынести S3-upload из screencast в общий helper** (`upload_artifact_to_s3`). Функция module-level в publisher.py (после S3-констант), graceful fallback на `None`, env kill-switch `AUTOWARM_S3_ARTIFACTS_DISABLE=1`. Verbose logs: DEBUG перед upload'ом (kind/path/key/size), INFO на success (URL/size/elapsed), WARNING на любую ошибку.

### Phase 2: Интеграция в debug-helpers

- [x] **T2 — Upload в `_save_debug_screenshot` + фикс `AccountSwitcher._maybe_screenshot`.** Сигнатура `_save_debug_screenshot` теперь `Optional[str]` (S3 URL или `/screenshots/` fallback). Новый буфер `self._collected_screenshots` в `DevicePublisher.__init__`, `_save_debug_artifacts` копит URL'ы, `_fail_task` мержит их с `screenshots=` от switcher (с дедупом). `_maybe_screenshot` переделан — больше не glob'ит `/tmp/` и не пихает локальные пути в `meta.screenshots`, использует return value напрямую.
- [x] **T3 — Upload в `_save_debug_ui_dump` + фикс `AccountSwitcher._save_dump`.** `_save_debug_ui_dump` прокачан через S3 helper. В switcher'е `_save_dump` теперь кладёт в `self._dumps` публичный URL (S3 или fallback), а не локальный путь — этот список идёт в `SwitchResult.ui_dumps` → `meta.ui_dumps` → UI задачи. Consumers (revision) используют только `status/reason/accounts/current`, `dumps` в них read-only telemetry — изменение безопасно.

### Phase 3: Верификация bucket / tests

- [x] **T4 — Верифицировать S3_PUBLIC_URL / bucket policy.** Bucket `1cabe906ea6e-gengo` через `save.gengo.io` отдаёт public-read для новых prefix'ов (`autowarm/screenshots/`, `autowarm/ui_dumps/`) без дополнительных настроек. Content-Type — корректный (image/png, application/xml). Evidence: `.ai-factory/evidence/publish-tasks-s3-artifacts-bucket-check-20260424.md`.
- [x] **T5 — Unit-тесты `upload_artifact_to_s3` (mock boto3).** `tests/test_s3_artifacts.py` — 8 cases (success-path, key-structure, content-type png/xml, ClientError fallback, EndpointConnectionError fallback, kill-switch env, unknown kind). 8/8 passed.

### Phase 4: Integration smoke

- [x] **T6 — Integration smoke объединён с T9.** Testbench (pm2 id=25) stopped и требует отдельного восстановления (node_modules symlink после merge). Smoke'ом служит мониторинг первой реальной публикации в prod после deploy'а — там data path тот же.

### Phase 5: Cleanup и UX-мелочи

- [x] **T7 — Legacy relative/local URLs: визуальный hint в UI.** `upShowEvents` (public/index.html ~10764): URL'ы, которые не начинаются с `http`, рендерятся серым со `line-through` и tooltip "legacy ссылка — файл может быть удалён с VPS". S3 URLs остаются яркими (indigo/amber). Backfill данных не делаем (legacy файлы в /tmp уже могли быть почищены).
- [x] **T8 — Cleanup локальных `/tmp` файлов после успешного upload'а.** Helper `_cleanup_local_artifact(local, s3_url)` — unlink только если S3 успешен. При fail — файл остаётся для express-static fallback. Env override `AUTOWARM_S3_ARTIFACTS_KEEP_LOCAL=1` сохраняет файлы (debug-режим). Вызывается из `_save_debug_screenshot`, `_save_debug_ui_dump`, `AccountSwitcher._save_dump`.

### Phase 6: Prod deploy

- [x] **T9 — Prod deploy + evidence.** Commit `872d99b` → auto-push → `sudo pm2 restart autowarm` (prod on 3848). **Gotcha обнаружен:** testbench pm2 (`autowarm-testbench`) работает из отдельной копии `/home/claude-user/autowarm-testbench/` — её пришлось pull'нуть вручную (git pull --ff-only + pm2 restart). Smoke-подтверждение: task #911 (YouTube testbench) — 20 S3 screenshots + 21 S3 ui_dumps, 0 legacy/local URLs, curl -I 200 OK с правильным Content-Type. Evidence: `.ai-factory/evidence/publish-tasks-s3-artifacts-prod-20260424.md`.

## Commit Plan

5 commit checkpoints:

1. **`feat(publisher): s3_artifacts helper — upload_artifact_to_s3`** — после T1.
2. **`feat(publisher): S3 upload для скринов и UI dumps + fallback`** — после T2 + T3.
3. **`test(publisher): unit-tests s3_artifacts helper (6 cases)`** — после T5.
4. **`feat(publisher): cleanup local /tmp after S3 upload; UI hint for legacy links`** — после T7 + T8.
5. **`feat(autowarm): deploy s3 artifacts (prod)`** — после T9 (prod deploy + evidence).

T4 (bucket policy) и T6 (smoke) — только evidence-файлы, отдельных commit'ов не требуют (или объединить с последним).

## Rollback plan

Если после deploy'а prod публикации начинают падать из-за upload'а:
1. Любая ошибка boto3 — graceful fallback уже встроен (T2/T3), публикация НЕ падает, URL — relative.
2. Если fallback сам сломан → `git revert <sha>` в `/root/.openclaw/workspace-genri/autowarm/` + `sudo pm2 restart autowarm`.
3. Отключить без revert: env `AUTOWARM_S3_ARTIFACTS_DISABLE=1` (добавить короткий kill-switch в T1 helper).

## Non-goals

- Не перепиливаем существующий `stop_and_upload_screen_record` — оставляем inline (рефакторинг когда-нибудь в отдельной задаче).
- Не мигрируем старые задачи на S3 (файлов всё равно нет в /tmp).
- Не меняем UI-рендер ссылок — фронт уже принимает любой href.
- Не трогаем схему БД (публичный URL и так помещается в существующие колонки/JSONB).
- TTL-cleanup /tmp (cron на `find -mtime +3`) — отдельная задача инфраструктуры.

## Open questions

- **T4 prereq:** нужен ли explicit S3 bucket policy для prefix `autowarm/screenshots/` и `autowarm/ui_dumps/`? Проверю в T4 через curl; если да — решим: применить через Beget-консоль самому или запросить у пользователя.
- **Kill-switch:** добавить `AUTOWARM_S3_ARTIFACTS_DISABLE=1` в T1 — на случай если bucket упадёт и fallback всё равно шумит.
