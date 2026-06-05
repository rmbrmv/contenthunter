# TT fail-триаж 2026-06-05 → OpenProject WP#256

Фокус: только TikTok, упавшие за сегодня (MSK). Источник — БД `openclaw`, `publish_tasks`.

## Сводка за день (TikTok, 44 задачи)

| status | count |
|---|---|
| done | 26 |
| **failed** | **13** |
| published_no_url | 2 |
| running | 2 |
| awaiting_url | 1 |

## Разбивка 13 failed по error_code

| error_code | error_class | count | природа |
|---|---|---:|---|
| **tt_inapp_upload_unreached** | ui_changed | **4** | **КОД ← выбрано для фикса** |
| phone_or_email_link_required | banned | 3 | ops (бан аккаунта, требует привязки телефона/почты) |
| tt_account_sheet_closed_before_parse | ui_changed | 1 | код |
| tt_caption_field_not_focused | ui_changed | 1 | код |
| process_interrupted | (null) | 1 | артефакт рестарта |
| tt_post_switch_verify_unrecoverable | ui_changed | 1 | код |
| tt_profile_tab_broken | ui_changed | 1 | код |
| tt_publish_button_not_activated | ui_changed | 1 | код |

Лидер кодовых падений — `tt_inapp_upload_unreached` (4). `phone_or_email_link_required` (3) — баны (ops, не код).

## Затронутые задачи (tt_inapp_upload_unreached)

15528 (theelitecornersspb / Art Estate_102), 15572 (dubairealestate062 / Ambassadori_112),
15586 (dubai.homes22 / Ambassadori_114), 15589 (tkachenko_biohack / Александр Ткаченко_36).
Девайс: RFGYB07YP7H @ шлюз 147.45.251.85.

## Логи (идентичны у всех 4)

```
account_switch ... done matched=True final=tt_fp_editor   (15589: final=tt_sa_fastpath)
url_capture_pre_snapshot: 5 ids
   <~90 секунд полной тишины>
[error] TikTok: in-app upload не достиг редактора за лимит   (category=tt_inapp_upload_unreached)
[error] Публикация завершилась с ошибкой
[handoff] Изменился интерфейс приложения — задача передана на ручную выкладку.
```
15589 дополнительно: 3× `TikTok: unknown state — детерминированный reset к ленте (am start)` (кап `MAX_INAPP_UNKNOWN_RESETS=3`).

## Скринкасты (15528 / 15572 / 15586 — идентичны)

Устройство доходит до **правильной in-app камеры TikTok** — режим **«ПУБЛИКАЦИЯ»** (это НЕ story-derail из WP#250) — и **застревает на ней** до таймаута.
- Превью галереи / «Загрузить» = **квадратный тайл в НИЖНЕ-ПРАВОМ углу** (последнее медиа).
- В **НИЖНЕ-ЛЕВОМ углу — карусель круглых эффектов / AI-фильтров**.

15589 — камера не задетектилась (`_tt_detect_camera_screen` False) → ветка (g) unknown → 3× reset → тот же терминал.

Кадры: `/tmp/tt-triage-0605/f15586_180.jpg`, `f15572_gap.jpg`, `f15528_gap.jpg`.

## Root-cause

`_tt_enter_upload_from_camera` (`publisher_tiktok.py:1203`) открывает галерею тапом в **НИЖНЕ-ЛЕВЫЙ** угол:
- скан clickable `x1 < 250 and y1 > 1900`;
- fallback `_TT_GALLERY_THUMB_COORD = (112, 2126)` (низ-лево, 1080×2340).

На текущей сборке TikTok вход в галерею («Загрузить») переехал в **НИЖНЕ-ПРАВЫЙ** угол, а низ-лево теперь = эффекты. Тап попадает в круглый эффект → галерея не открывается → state-machine `_tt_inapp_upload_from_camera` крутит ветку (e) camera до `MAX_INAPP_UPLOAD_ITERATIONS=12` (ветка ничего не логирует на итерацию → 90с тишины) → честный fail + handoff.

Это **новый root-cause** того же кода `tt_inapp_upload_unreached` (WP#203 закрывал другие драйверы: ложный экран профиля, storyservice-stuck).

## Направление фикса (НЕ реализовано — отдельная задача)

Входить в галерею по тайлу в НИЖНЕ-ПРАВОМ углу. Робастно: детектить gallery/upload-тайл как **прямоугольный (не круглый) clickable в нижней полосе ПРАВЕЕ кнопки записи**, либо по `content-desc` «Загрузить»/«Upload»/«Альбом»; убрать хардкод низ-лево. Под kill-switch. TDD + canary на телефоне.

Заведено: **OpenProject WP#256** (тип Ошибка, статус Бэклог).
