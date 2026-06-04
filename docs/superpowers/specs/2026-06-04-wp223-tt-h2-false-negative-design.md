# WP#223 — TikTok H2 false-negative детекции публикации (дизайн)

**Дата:** 2026-06-04
**OpenProject:** #223 (Ошибка, проект 3), статус «В разработке», assignee Данил
**Фоллоу-ап:** WP#218 (H1, «Опубликовать» мис-тап — Тестирование). Связано: WP#181 (IG stale-uiautomator post-mortem probe), WP#226 (post-publish промо-модалки), WP#204 (URL-capture).
**Код:** `delivery-contenthunter` (autowarm), `publisher_tiktok.py` + `server.js`. Доки: `rmbrmv/contenthunter`.

## Проблема

После лечения доминантного H1 (мис-тап «Опубликовать») остаётся вторичный кластер **H2 (~15%, 2/13): false-negative детекции при РЕАЛЬНО прошедшей публикации** → ложный fail + риск дубля при ручной переотправке. Скринкасты 02.06:

- **task 14040**: видео уже в ленте («axilor_brand 1 с. назад»), но модалка **«Синхронизируйте контакты»** (Не разрешать/ОК) перекрывает success-детект → таймаут вместо done.
- **task 14144** (clickpay_express): профиль с залитым видео, но **нечитаемый uiautomator-дамп** (stale) → маркеры не матчатся → false-negative.

Плюс вторичная гигиена: тестбенч-задачи авто-удаляются из `publish_tasks` на стадии `awaiting_url` РАНЬШЕ записи финального статуса/URL (смок #14496) → теряются тестбенч-результаты/скринкасты.

## Контекст по коду (подтверждено разведкой)

- `_tt_screen_indicates_publish_done(ui)` (publisher_tiktok.py:2654) уже принимает как доказательство публикации: `_tt_post_publish_success_screen`, visibility-confirm, music-rights, notif-modal (WP#226), amplify (WP#226), navbar-shell (OP#236).
- `_wait_upload_confirmation` дисмиссит оверлеи единообразно: notif→`KEYCODE_BACK`; contacts-perm/amplify/promo-inbox→handler с `cap → inferred_success`.
- **Дыра H2.1**: `_detect_tt_contacts_perm` ловит только OS-диалоги (`_TT_PERM_DIALOG_VARIANTS` = «доступ к контактам», «доступ к списку ваших друзей»). In-app модалка **«Синхронизируйте контакты»** не покрыта ничем.
- **Дыра H2.2**: на профиле нет post-mortem пробы. В IG (WP#181, publisher_instagram.py:3591) проба читает `topResumedActivity` через dumpsys (ground-truth, независимо от uiautomator) с grace-окном и поллингом → при уходе из ModalActivity = inferred success без fail-событий.
- **#3**: прод-DELETE по `publish_tasks` **отсутствует** во всём autowarm-репо и в `/home/claude-user/autowarm-testbench` (только в тестах). Источник — вне просмотренных репо: кандидаты — DB-триггер/правило, crontab, процесс-чистильщик, либо smoke-harness. `publish_tasks` имеет колонки `testbench BOOLEAN` и `is_canary BOOLEAN`.

## Решения (согласованы с Данилом)

| # | Вопрос | Решение |
|---|--------|---------|
| Объём | Что в WP | Все три части (H2.1 + H2.2 + #3) |
| H2.1 | Трактовка «Синхронизируйте контакты» | **Только дисмисс** (консервативно), НЕ доказательство публикации |
| H2.2 | Стратегия stale-dump на профиле | **Dumpsys-проба** (зеркало WP#181) |
| B | inferred-success путь H2.2 | Как другие inferred_success TT (терминальный успех без URL, URL добирает url-поллер) |

## Компонент A — H2.1: дисмисс «Синхронизируйте контакты» (dismiss-only)

**Детектор** `_detect_tt_contacts_sync_modal(ui_xml) -> bool`:
- Substring-заголовок «Синхронизируйте контакты» (+ EN-зеркало, если встретится) в новой константе `_TT_CONTACTS_SYNC_MARKERS`.
- Требует clickable-кнопку дисмисса из `_TT_CONTACTS_SYNC_DISMISS_LABELS = ['Не разрешать', "Don't allow"]` (предпочтительно) либо «ОК».
- Отдельный от `_detect_tt_contacts_perm` — не трогаем OS-диалог-вариант.

**Wire в wait-loop** (по образцу notif-обработчика, рядом с contacts-perm):
- Тап по «Не разрешать» (приоритет) → fallback `KEYCODE_BACK` → `continue`.
- Per-task счётчик `_contacts_sync_iter` + cap `MAX_TT_CONTACTS_SYNC_ITERATIONS=5`; ресет в `_init_wait_upload_overlay_state`.
- **НЕ** добавляется в `_tt_screen_indicates_publish_done` — после снятия оверлея успех подтверждают существующие navbar-shell / UPLOAD_OK маркеры на следующей итерации.
- Kill-switch `TT_CONTACTS_SYNC_MODAL_DISMISS_ENABLED` (default ON).

## Компонент B — H2.2: post-mortem dumpsys-проба (зеркало WP#181)

На **границе таймаута** wait-loop, перед честным fail (точка, где сейчас пишется `tt_upload_confirmation_timeout`), при долгом transit + нечитаемом/stale дампе:
- Grace-окно (`TT_UPLOAD_POSTMORTEM_GRACE_S=20`, poll `TT_UPLOAD_POSTMORTEM_POLL_S=5`) поллит `topResumedActivity`.
- Если TT ушёл с upload/editor-активности на главную shell/профиль-активность → **inferred success** (fall-through в success-путь, как amplify/notif), fail-события не пишем.
- Inconclusive (не подтвердилось за окно) → **честный fail** как сейчас. Новых ложных success-путей не вводим.

**Открытая деталь для плана (разведка):** текущий `_tt_foreground_pkg()` (publisher_tiktok.py:912) достаёт только пакет; редактор и фид — один пакет. Пробе нужна **активность** (компонент из `topResumedActivity`). В плане: определить по дампам/разведке имя главной shell/feed-активности (`MainActivity`/`SplashActivity`-host) vs publish/edit-активности (`...VideoPublishActivity`/`...edit...`). Хелпер `_tt_left_editor_activity(top_resumed_activity) -> bool` (позитивный матч на shell-активность ИЛИ негативный — отсутствие editor/publish-активности при живом TT-пакете).

**Kill-switch** `TT_UPLOAD_POSTMORTEM_PROBE_ENABLED` (default ON).

## Компонент C — #3: тестбенч авто-DELETE (разведка → гард)

**Фаза C1 — разведка (план-степ):** локализовать источник DELETE. autowarm/testbench-репо исключены. Проверить:
1. Живую БД на триггеры/правила `publish_tasks`: `SELECT tgname, tgrelid::regclass, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='publish_tasks'::regclass;` + `pg_rules`.
2. `crontab -l` (root и claude-user), systemd-таймеры.
3. При необходимости — временный audit (statement-log/триггер-логгер) чтобы поймать DELETE-агента на следующем smoke.

**Фаза C2 — гард:** после локализации — не удалять до терминального статуса. Форма зависит от C1:
- если внешний процесс/крон — добавить условие `status IN (терминальные)` в его DELETE;
- если DB-триггер — скорректировать условие;
- запасной вариант — защитный BEFORE DELETE триггер, блокирующий удаление `testbench=TRUE AND status IN ('pending','running','processing','awaiting_url')`.
- Гард **не** должен ломать легитимную чистку canary/старых терминальных testbench-строк.

## Тестирование (TDD)

- **A:** unit-тест `_detect_tt_contacts_sync_modal` (XML-фикстура модалки + негативы: OS-диалог contacts-perm, чистый фид); тест wait-loop-обработчика (дисмисс→continue, cap); тест что детектор НЕ попал в success-предикат.
- **B:** unit-тест пробы с mock `adb`/`dumpsys` (уход на shell-активность→inferred success; editor-активность→честный fail; inconclusive→честный fail).
- **C:** репро через testbench-smoke; проверка что строка доживает до терминала; гард-тест на не-удаление pre-terminal.
- Регрессия полного TT-набора (как в WP#226/#218 — порядка ~460+ зелёных).

## Риски и безопасность

- Все изменения под kill-switch'ами default ON (мгновенный откат через env).
- **A** — dismiss-only: нет риска ложного success (модалка не считается доказательством).
- **B** — срабатывает только на границе would-be-fail; inconclusive → честный fail; путь идентичен проверенному WP#181.
- **C** — гард сужен по статусу/флагу, не трогает легитимную чистку.

## Деплой (по памяти проекта)

- Код autowarm = `delivery-contenthunter`; прод-каталог `/root/.openclaw/workspace-genri/autowarm` (claude-user, git pull без sudo).
- Publisher спавнится per-task → PM2-restart обычно НЕ нужен для python-правок; для server.js-изменений (если #3 там) — `sudo pm2 restart` id35.
- Код-правки вести в ИЗОЛИРОВАННОМ worktree (общий checkout = гонка с параллельными сессиями).
