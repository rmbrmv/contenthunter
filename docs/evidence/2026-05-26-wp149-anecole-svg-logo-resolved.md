# WP #149 — Anecole не публикуется с 06.05 (битый SVG-логотип) — уже устранено + проверено re-queue

**Дата:** 2026-05-26
**Контекст:** авто-исполнитель прислал бриф `contenthunter_autoexec/briefs/149/brief.md` с классификацией B («нужно решение/уточнение»): кто предоставит корректный PNG для схем 4/5, что делаем — заменить PNG или убрать SVG-оверлей, где правим ассет, харднинг в #151? Перед любым действием — свёрка брифа с прод-данными и кодом воркера.
**Метод:** чтение прод-кода воркера уникализации (`/root/.openclaw/workspace-genri/autowarm/unic-worker`, main @1af91ce+), скачивание и инспекция байтов реального ассета логотипа, разбор `unic_tasks`/`unic_results`/`publish_queue` по project_id=84, проверка cairosvg в прод-окружении, live re-queue застрявшей задачи. DB `openclaw@localhost`.

---

## TL;DR

- Первопричина подтверждена и сужена точно: падал **вход FFmpeg #3 — бренд-логотип** (`brand/84/logo/….png`, но содержимое `<svg …>`). `Invalid PNG signature 0x3C73766720776964` (=ASCII `<svg wid`) → все схемы с логотипом (4/5/6) падали → `unic_tasks.error` → контент не генерился → `publish_queue` пуст с 06.05.
- **Логотип уже починен без нашего участия:** `validator_brand_profiles` (project 84) обновлён **2026-05-25 12:53** (через ~1 ч после создания WP 11:49). Сейчас по `logo_url` — валидный PNG 900×900 RGBA (скачан, проверены байты + `ensure_png_raster` → конвертировать нечего).
- **Системный харднинг уже в проде (#151 Готово):** воркер (PR #105) вызывает `normalize_asset` на логотипе и паттерне — любой остаточный SVG растеризуется в PNG до FFmpeg. cairosvg 2.8.2 в прод-окружении работает, kill-switch `UNIC_SVG_RASTERIZE_ENABLED` включён по умолчанию.
- **Все 4 вопроса брифа сняты:** новый PNG ни от кого не нужен (уже валидный), «убирать SVG-оверлей» не нужно, ассет уже исправлен в бренд-профиле/S3, харднинг уже сделан в #151.
- Осталась лишь застрявшая задача `unic_tasks` id 2639 (`error` с 19.05, сама не перезапускается). **Re-queue выполнен → 3/3 схемы `done`**, без `Invalid PNG signature`.

**Решение:** код не пишем. WP #149 → «Тестирование» (первопричина устранена логотипом 25.05 + харднингом 26.05; re-queue подтвердил генерацию). Реальная выкладка дальше зависит от аккаунтов (**#150**).

---

## Evidence

### 1. Битый ассет = логотип (вход FFmpeg #3), не «схема»

Порядок входов в `worker.py:generate_ffmpeg`: `0`=original, `1`=overlay_video, `2`=overlay_audio, `3`=**logo**, `4`=pattern. Глобальные пулы непусты (video 10×mp4, audio 24×mp3, pattern 20+×png), значит индексация держится и **#3 = логотип**.

`unic_tasks.meta->scheme_errors` задачи 2639 (последний прогон 2026-05-19 06:17):
```
схема 4/5/6: [png @ ...] Invalid PNG signature 0x3C73766720776964.
Error while decoding stream #3:0: Invalid data found when processing input
```
`0x3C73766720776964` = ASCII `<svg wid`. Паттерн глобальный и `.png` (другие проекты здоровы — 10/14 `done` сегодня), значит project-specific SVG был именно у логотипа Anecole.

### 2. Логотип сейчас — валидный PNG (починен 25.05)

```
validator_brand_profiles project 84:
  logo_url   = …/brand/84/logo/6888379236544ba389fccd1284947a3d.png
  updated_at = 2026-05-25 12:53:21   (WP создана 2026-05-25 11:49)
```
Скачанный файл: `PNG image data, 900 x 900, 8-bit/color RGBA`, корректная сигнатура `\x89PNG`. Прогон через прод `svg_raster.ensure_png_raster`: `looks_like_svg=False`, `converted=False` — файл уже чистый PNG.

### 3. Харднинг воркера в проде (safety net для остаточных SVG)

- `worker.py:423` и `:428` — `await asyncio.to_thread(normalize_asset, p)` на logo и pattern.
- `worker.py:163-172` `normalize_asset` → `svg_raster.ensure_png_raster` (sniff `<svg`/`<?xml` → cairosvg 1024px). Kill-switch `UNIC_SVG_RASTERIZE_ENABLED` (default `1`).
- Прод-окружение: `cairosvg 2.8.2` импортируется системным `python3` (воркер под root-PM2 `unic-worker`, exec cwd `…/unic-worker`).
- Деплой подтверждён: autowarm main содержит `1af91ce Merge PR #105 …svg-logo-rasterization`.

### 4. Таймлайн project_id=84

| Что | Период |
|---|---|
| `unic_tasks` `done` (здоров) | 2026-04-15 … **2026-05-06** (16 задач) |
| `unic_tasks` `error` (SVG-логотип) | 2026-05-07 … 2026-05-19 (19 задач) |
| Последняя задача (id 2639, схемы 4/5/6) | 2026-05-19 06:17, после — задач нет |
| `publish_queue` `done` (последняя выкладка) | до **2026-05-06** (44 done, 67 failed, всё ≤06.05) |

### 5. Live re-queue (эмпирическое подтверждение)

`UPDATE unic_tasks SET current_status='pending', error_message=NULL, schemes_done=0, schemes_error=0 WHERE id=2639` (только последняя задача; старые дубли не трогали).

Воркер подхватил за один цикл поллинга. Прогресс: `processing` → `done=1` → `done=2` → **`done` (done=3, err=0)** за ~2 мин.
```
unic_results task_id=2639:
  scheme 4 → …/20260526134402_t2639_3478cf02_s4.mp4  done
  scheme 5 → …/20260526134446_t2639_3478cf02_s5.mp4  done
  scheme 6 → …/20260526134535_t2639_3478cf02_s6.mp4  done
```
ffprobe scheme-4: h264 + aac, 850×1410, 31.8с, 6.37 MB — валидное видео. Никакого `Invalid PNG signature`.

---

## Осталось / границы

- 3 `unic_results` ждут авто-привязки (`assignUnicResultsToQueue`, 30-мин крон → `publish_queue` → `dispatchPublishQueue` → `publish_tasks`). Past-slot guard дропает прошедшие слоты — спама старыми постами не будет.
- **С 19.05 авто-свип не создавал новых задач уникализации для 84** — постоянную генерацию/выкладку, вероятно, держит зависимость от аккаунтов (**#150**). Это вне scope #149 (тот про SVG-ассет).
- Харднинг (валидация типа ассета) — в **#151** (Готово), не дублируем здесь.
