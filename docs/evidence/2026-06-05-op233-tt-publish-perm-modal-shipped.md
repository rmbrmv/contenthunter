# OP#233 — ложный `tt_publish_button_not_activated`: пост-публикационная permission-модалка

**SHIPPED+DEPLOYED 2026-06-05** · delivery-contenthunter `main` merge `2b7693e`
(branch `op233-tt-fb-friends-perm-success`, commit `1f948b9`) · прод-checkout
`/root/.openclaw/workspace-genri/autowarm` обновлён · `publisher.py`/`publisher_tiktok.py`
spawn'ятся per-task → PM2-рестарт не нужен · OP#233 → Тестирование.

## Симптом

`tt_publish_button_not_activated` — «кнопка „Опубликовать“ не активирована (экран
редактора не сменился после тапа)» → handoff в ручную = **риск дубля**.

Исходный диагноз триажа («промах fallback-тапа по null AI-координатам») оказался
**симптомом, не корнем**.

## Root-cause (доказан скриншотами прод-артефактов)

Тап «Опубликовать» **УСПЕШЕН** — пост виден в ленте `«N c. назад»` — но TikTok сразу
поднимает permission-модалку поверх свежей ленты:

| task | аккаунт | вариант модалки | кнопки |
|------|---------|-----------------|--------|
| 15638 | easy_backcare | «Разрешить TikTok доступ к списку ваших друзей в Facebook и почтовому адресу?» | Не разрешать / OK |
| 15615 | bodyrelieflab_1 | то же (FB-friends) | Не разрешать / OK |
| 15603 | back_relax_tools | «…разрешите доступ к контактам в настройках устройства» | Открыть настройки / Не разрешать |

Когда foreground = диалоговое окно, `uiautomator` дампит **только диалог** →
navbar/feed-маркеры отсутствуют → `_tt_screen_indicates_publish_done()` = `False` →
`_tt_verify_publish_left_editor()` неинформативен (`tt_publish_verify_inconclusive`) →
retap-цикл: descendant-кнопка найдена на реальных координатах, затем `ai_find_tap`
отдаёт `{x:null,y:null}` → слепые fallback-тапы (все «inconclusive») → cap → ложный
`tt_publish_button_not_activated`.

Трасса (task 15638):
```
08:17:10  кнопка публикации найдена (descendant) pos=(798,2103)   ← реальная кнопка, тап
08:17:18  пост-тап дамп неинформативен (ни success, ни редактор)  ← FB-модалка не распознана
08:17:39  ai_find_tap_no_coords {x:null,y:null}                    ← AI fallback null
08:17:40+ FALLBACK тапы … все «неинформативен»
08:19:19  ERROR tt_publish_button_not_activated
```

## Фикс

Модалка **уже** детектится `_detect_tt_contacts_perm` (WP #82 — оба варианта в
`_TT_PERM_DIALOG_VARIANTS`: «доступ к контактам» и «доступ к списку ваших друзей») и
штатно дисмиссится в `_wait_upload_confirmation` (`TT_PERM_DIALOG_HANDLER_ENABLED`,
тап «Не разрешать»). Но та wait-петля достигалась лишь **после** принятия пост-тап
верификацией. Единственный пробел — verify-предикат не считал perm-диалог сигналом
публикации.

Добавлен `_detect_tt_contacts_perm` как publish-done в
`_tt_screen_indicates_publish_done` за kill-switch
`TT_PUBLISH_PERM_DIALOG_SUCCESS_ENABLED` (default ON) — по образцу WP#226
(notif/amplify) и OP#236 (navbar-shell). **Layout-independent** (substring +
tap-by-text, без координат → не повторяет урок #256 про зеркальные раскладки).

## Охват

После деплоя OP#236 (04.06 08:23 UTC) **100% (3/3)** остаточных
`tt_publish_button_not_activated` = эта perm-модалка (оба варианта). Всплеск 16 на
06-03 — кейс OP#236 (navbar-shell, до его деплоя), уже закрыт.

## Тесты

`tests/test_publisher_tt_fb_friends_perm_success.py` — 10 тестов TDD (RED→GREEN):
детектор обоих вариантов; `_tt_screen_indicates_publish_done`; `_tt_verify_publish_left_editor`
(advance без BACK); kill-switch ON/OFF; негативы (editor и unrelated-диалог «Не
разрешать»/«OK» с не-perm-заголовком → False). Регрессия `publisher_tt` — 461 passed.
Скорректирован source-order guard в `test_publisher_tt_overlay_handlers.py` (поиск
wait-loop C-handler от `inapp_idx`, т.к. появился второй вызов `_detect_tt_contacts_perm`
в verify-предикате). 1 пред-существующий энвайронмент-фейл `test_publish_guard`
(DB-unpack) — не связан.

## Остаток

Live-verify на след. прод-появлении модалки (~3/сут). Канарейка реальной публикацией
не форсилась: модалка появляется вероятностно post-publish, а правка **инертна на
нормальном пути** (новая ветка срабатывает только при матче perm-диалога).
