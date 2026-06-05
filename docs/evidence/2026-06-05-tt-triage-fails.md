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

## Первоначальное направление фикса (оказалось НЕВЕРНЫМ — см. резолюцию)

Гипотеза из прод-скриншотов: тайл галереи переехал в НИЖНЕ-ПРАВЫЙ угол; фикс = тапать туда. **Канарейка опровергла это** (ниже).

Заведено: **OpenProject WP#256**.

---

## РЕЗОЛЮЦИЯ — SHIPPED+DEPLOYED+КАНАРЕЙКА-VERIFIED (05.06)

### Канарейка вскрыла настоящий root-cause (глубже триажа)

Раскладка in-app камеры TikTok **ЗЕРКАЛЬНА между устройствами** (разные версии приложения):

| устройство | тайл галереи | пример |
|---|---|---|
| прод **RFGYB07YP7H** (падавшие 15528/15586) | **СПРАВА** — центр (879,1849), bbox [806,1777][951,1922] | старый код тапал ПУСТО слева → fail |
| testbench **RF8YA0W57EP** | **СЛЕВА** — центр (112,2126) | эффекты справа |

resource-id обфусцированы и **различаются между версиями** (галерея `ce9` vs `zne`, запись `r3r` vs `rts`) → как якорь непригодны.

### Пивот v1 → v2

- **v1** (хардкод низ-право `(878,1849)`) — **провалил канарейку** на testbench RF8YA0W57EP: тапнул эффект, регрессировав *рабочий* флот (на этих устройствах старый код работал). Канарейка остановила выкат.
- **v2** — раскладко-независимый детектор `_tt_find_gallery_upload_tile`: галерея = **ОДИНОКИЙ квадратный тайл** (cy>1550, 90≤w≤280) на стороне записи, **противоположной карусели эффектов** (несколько тайлов); исключает Button-запись и узкие срезы; неоднозначно → None → легаси-fallback. Kill-switch `TT_GALLERY_ENTRY_TILE_DETECT_ENABLED` (default ON).

### Валидация

- 2 **реальных дампа** обеих раскладок как фикстуры (`tests/fixtures/tt_camera_gallery_{right,left}.xml`) — оба зелёные.
- 94 inapp-теста + **720 TT-регрессия** (0 fail).
- **Канарейка task 15763 на реальном телефоне RF8YA0W57EP → `done`**: галерея открылась → видео выбрано (56s) → редактор → caption → **видео опубликовано** (`tiktok.com/@user70415121188138/video/7647842763647552798`).

### Деплой

Merge **7817868** в `main` delivery-contenthunter (origin/main параллельно ушёл `3e41b82`→`88655f7`, `publisher_tiktok.py` не конфликтовал); прод-дерево обновлено, **PM2-restart не нужен** (publisher per-task spawn); kill-switch активен по дефолту. **OP#256 → Тестирование.**

### Урок

Координатные фиксы TikTok-камеры **не универсальны** (зеркальные раскладки/версии) — канарейка на реальном телефоне обязательна, она поймала неверный v1 до выката на флот. Память: `project_tt_triage_2026_06_05`.

### Не-кодовое из триажа → оператору

`phone_or_email_link_required` (баны, 4 аккаунта) → **OpenProject WP#266** на Анастасию (простым языком, привязка телефона/почты). Память: `feedback_ops_tasks_to_anastasia`.

### Остаток

Наблюдение done-rate TT по in-app upload ~сутки (правая раскладка проверена фикстурой; живое подтверждение — по статистике прода) → затем OP#256 → Готово.
