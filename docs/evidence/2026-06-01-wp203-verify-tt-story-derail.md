# WP#203 verify — TikTok story-derail / caption-focus fix (2026-06-01)

Статус по итогу: **ЧАСТИЧНО ДЕРЖИТСЯ → остаётся «Тестирование»** (root cause устранён, но всплыл новый остаточный драйвер на пост-caption редакторе).

## Прод реально на фиксе
- pm2 id35 `autowarm`, exec cwd `/root/.openclaw/workspace-genri/autowarm`.
- git HEAD = `ec44cf8` (вершина wp203), branch main, чисто относительно origin/main.
- Хелперы wp203 в `publisher_tiktok.py`: `_tt_detect_story_derail` (740), `_tt_inapp_upload_from_camera` (826), EditText caption tap (797/2341), стейт-машина (868+), миграция 5 кодов.
- Kill-switch `TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED` default `true`, в .env не переопределён → ВКЛ.
- Деплой-коммит ec44cf8 закоммичен 2026-05-31 19:18 → cutoff пост-деплоя берём 31.05 19:00.

## Динамика TT (non-testbench, publish_tasks)
Per-day done / failed:
| день | done | failed | total |
|------|------|--------|-------|
|26.05|72|141|223|
|27.05|70|97|173|
|28.05|68|31|104 (success 70.2%)|
|29.05|44|30|84|
|30.05 (обвал)|2|86|89|
|31.05|21|174|203|
|01.06 (до 07:00)|12|24|47 (success 36.8%)|

Пост-деплой окно (31.05 19:00 → now): done=31, published_no_url=10, failed=74 → **success 35.7%**.

## Целевые коды story-derail — УСТРАНЕНЫ
Пост-деплой (31.05 19:00→now):
- `tt_caption_field_not_focused`: **1** (было 55 на 30.05, 65 на 31.05-день)
- `tt_storyservice_fg_stuck`: 2
- `tt_story_derail_unrecoverable`: 0
Оригинальный root cause (TikTok сам уводит в Stories + caption не фокусится) — снят.

## Реальные публикации подтверждены
31 done пост-деплой, ВСЕ с реальным post_url `tiktok.com/@.../video/...` (0 done-без-url).
Смок testbench #12813 (№19) = done с реальным post_url.

## НОВЫЙ остаточный драйвер (визуально по скринкастам)
Топ пост-деплой фейлы: `tt_upload_confirmation_timeout` (33), `tt_inapp_upload_unreached` (14).
Все timeout-таски имеют caption-события (story-derail снят, caption напечатан).

Кадры (12-мин клипы, флоу завис до timeout):
- **task 13085 irbis.academy** (`tt_upload_confirmation_timeout`): дошёл до caption-экрана, caption напечатан (#театральныезанятиядлядетей …), ADB Keyboard ON, обложка «Предпросмотр» загружена — но завис на **открытой панели подсказок хэштегов** («# Хэштеги / @ Упомянуть» + список), не сворачивает её, не доходит до «Опубликовать». 11:33→11:40 кадры идентичны → timeout.
- **task 13074 spbluxestate** (`tt_upload_confirmation_timeout`): дошёл до ПОЛНОГО пост-экрана (caption + «Добавить ссылку» + «Эту публикацию могут просматривать все» + «Другие параметры»), но поверх кнопки «Опубликовать» всплыла **bottom-sheet «Поделиться / После публикации TikTok откроет…»** (Facebook/SMS) — не дисмиссит, не тапает Публиковать → timeout.
- **task 13098 dubairealestate062** (`tt_inapp_upload_unreached`): признаки FALSE-NEGATIVE — пост-мортем-проба попала на профиль/ленту с контентом и in-app share-sheet своего же видео; код фейла под вопросом (возможна недоучтённая публикация).

Скринкасты: save.gengo.io/autowarm/screenrecords/tiktok/task1309{8}, task1307{4}, task1308{5}.

## Вывод
- Фикс wp203 устранил story-derail и caption-focus (целевые коды 55-65→0-2/день), вытащил TT из катастрофического обвала (done 2→31+), даёт реальные публикации с URL.
- НО success-rate ~36% против baseline 70% (28.05): новый блокер — флоу залипает на пост-caption редакторе (открытая панель хэштегов / share-after-publish bottom-sheet перекрывает «Опубликовать») → `tt_upload_confirmation_timeout`. Плюс часть `tt_inapp_upload_unreached` похоже false-negative (контент опубликован, проба не распознала).
- Это НЕ #204 (URL-capture) и НЕ #205 (switcher). Нужна iter4 #203 (или спин-офф): collapse hashtag-suggestion panel + dismiss «Поделиться» bottom-sheet + детерминированный тап «Опубликовать»; разобрать false-negative в `tt_inapp_upload_unreached`.

→ #203 остаётся «Тестирование».
