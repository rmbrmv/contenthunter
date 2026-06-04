# Триаж TikTok-фейлов за 04.06.2026

Срез на ~11:00 МСК (день ещё не закрыт). Источник: прод host-PG `openclaw.publish_tasks`, фильтр `platform='TikTok'`, `(updated_at AT TZ UTC AT TZ Moscow)::date='2026-06-04'`.

## Статусы за сегодня

| status | n |
|---|---|
| failed | 31 |
| done | 17 |
| awaiting_url | 3 |
| running | 2 |
| pending | 1 |

## Распределение error_code среди failed

| error_code | error_class | n | вердикт |
|---|---|---|---|
| tt_inapp_upload_unreached | ui_changed | 12 | фикс WP#203 iter6 (PR#156) влит 10:42 МСК; все 12 падений 08:01–10:27 — **до деплоя**; бакет в верификации |
| phone_or_email_link_required | banned | 4 | ops/аккаунты (TikTok требует привязку телефона/почты) |
| **tt_publish_button_not_activated** | ui_changed | **4** | **выбран для фикса → OP #236** |
| tt_account_not_in_list | ui_changed | 2 | ops (аккаунты не залогинены, ср. WP#232) |
| tt_caption_field_not_focused | ui_changed | 2 | хвост, наблюдать |
| tt_storyservice_fg_stuck | ui_changed | 1 | singleton |
| adb_device_not_ready | device_unreachable | 1 | singleton (девайс) |
| tt_upload_confirmation_timeout | ui_changed | 1 | singleton |
| tt_account_switcher_wrong_foreground | ui_changed | 1 | singleton |
| tt_open_list_probe_stale_ui | ui_changed | 1 | singleton |
| tt_profile_tab_broken | ui_changed | 1 | singleton |
| (null) | (null) | 1 | singleton |

## Выбранный баг: tt_publish_button_not_activated (4) → OP #236

Объёмный лидер `tt_inapp_upload_unreached` исключён — по нему сегодня уже задеплоен фикс (iter6), падения пре-деплойные. Следующий код-фиксящийся бакет без активного фикса — `tt_publish_button_not_activated`.

### Root cause (логи + скринкасты 15214, 15202)

Публикация **реально проходит**, но success-детектор её не распознаёт:

1. Caption введён, XML находит кнопку «Опубликовать» `pos=(798,2103)`, тап проходит.
2. TikTok уходит на пост-публикационный экран: вкладка **«Друзья»** с кружком **«99%»** (загрузка), затем играющий опубликованный ролик; либо вкладка **«Входящие»**.
3. Детектор: `пост-тап дамп неинформативен (ни success, ни редактор)` — экран не классифицируется как success.
4. Воркер считает кнопку ненажатой → `ai_find_tap_no_coords resp={x:null,y:null}` → FALLBACK на хардкод `(816,2130)/(825,2145)` (попадают по нижнему навбару).
5. Исчерпание попыток → `tt_publish_button_not_activated` → handoff в ручную.

**Итог: ложный fail на уже опубликованном ролике → перевыкладка оператором → дубль.**

### Evidence (кадры)

- **task 15214** (RFGYA0V7MYV / myprimeestate): кадр после тапа — вкладка «Друзья» + кружок «99%» (загрузка ролика); следом — опубликованный ролик в ленте (лайки/комменты/«Ссылка»). Скринкаст `task15214_fail_screenrec`.
- **task 15202** (RF8Y80ZT5GT / tkachenko_biohack): финал на вкладке «Входящие». Скринкаст `task15202_fail_screenrec`.

### Связь

- Уточняет/перекрывает **#233** (там RC = «промах fallback-тапа при null-координатах» — downstream-симптом; корень — нераспознанный пост-публикационный success-экран).
- Семейство ложно-негативных success-детектов TikTok: **#226** (постмодалка), **#218**.

### Направление фикса

Расширить `_tt_screen_indicates_publish_done` на новые пост-публикационные сигнатуры (вкладка «Друзья»/«Входящие» в foreground + кружок прогресса NN% сразу после тапа «Опубликовать»). При обнаружении — не ретапать, фиксировать success + обычный URL-capture. За kill-switch.

### Статус реализации — SHIPPED+DEPLOYED 04.06 → Тестирование

Реализован модульный предикат `_tt_main_navbar_shell(ui)` в `publisher_tiktok.py`: True при двух editor-absent метках главного навбара («Главная»+«Входящие» / «Home»+«Inbox»). «Друзья» как маркер **не используется** — это ещё и значение видимости в редакторе (коллизия). Подключён в `_tt_screen_indicates_publish_done` за kill-switch `TT_PUBLISH_NAVBAR_SHELL_SUCCESS_ENABLED` (default ON). Распознаётся в top-of-loop проверке (`publisher_tiktok.py:3278`) и пост-тап verify (`:2691`) → success-break **до** fallback-тапов.

- Код: `GenGo2/delivery-contenthunter`, **PR #158 → main `b4d9a9f`**; прод pull в `/root/.openclaw/workspace-genri/autowarm` (publisher per-task spawn → PM2-рестарт не нужен).
- TDD: 17 новых тестов (`tests/test_publisher_tt_navbar_shell_success.py`), регрессия TT-сьют 70/70, полный публикатор-юнит 462 passed (3 пре-существующих фейла probes IG/tt не связаны).
- OpenProject **#236 → «Тестирование»**; backlog **#233** перекрыт (RC уточнён: не «промах fallback-тапа», а нераспознанный навбар-шелл).
- Verify (~сутки): тренд `tt_publish_button_not_activated` ↓ + событие `tt_publish_confirmed_in_share_loop`.
