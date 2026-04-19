# T6 — Структурный аудит `/tmp/autowarm_worker`

**Клон:** `/tmp/autowarm_worker`, last commit `3a19703` 2026-04-17.
**Стек:** Python 3, Poetry, Airtest + Yosemite IME, Celery + Redis, SQLAlchemy ORM, Docker.

## Модули и размеры

```
app/
├── celery.py                       32 строки    — Celery config (timeouts, queue, worker recycling)
├── celery_signals.py                -          — prefork hooks
├── consts.py                        -          — SCREEN_W/H, IG_FOLDER, TIKTOK_FOLDER, paths к image-templates
├── db.py                            -          — SessionMaker
├── entrypoints/
│   ├── worker.py                  148 строк    — Celery task `run_autowarm(device, day, platform)` + subprocess
│   └── cmd.py                      97 строк    — CLI: `python -m app.entrypoints.cmd --day N --device … --social …`
├── exceptions.py                    4 строки   — 1 class `ImageForTapNotFound`
├── logging_setup.py                 -          — structured JSON logging format
├── models.py                        -          — ORM models
├── modules/
│   ├── humanize_with_coords.py    635 строк   — **главный модуль**: HumanizeActions class
│   ├── ig/
│   │   ├── day1.py                 22 строки   — h.close_social_media(); h.run_search_and_watch_flow()
│   │   ├── day2.py / day3.py / day4.py
│   ├── tiktok/
│   │   ├── day1.py                 61 строка   — как ig/day1 + comments_list
│   │   ├── day2.py … day4.py … day4_6.py
│   │   └── publish_video.py       138 строк   — публикация видео через Airtest (sans LLM)
│   └── yt/{day1…day4}.py
├── repositories/
│   ├── autowarm_tasks.py           15 строк    — SQLAlchemy update_status(task_id, new_status)
│   └── raspberry.py                 -          — get_raspberry_info(device_number) → {host, adb_port}
└── services/
    └── subject_service.py           -          — extract_device_id, get_random_hashtag_name_by_device_id
```

## Ключевые методы `HumanizeActions` (humanize_with_coords.py)

| Метод | Назначение | Строки |
|---|---|---:|
| `__init__(device_uri)` | auto_setup Airtest + Yosemite IME + _cleanup_device + portrait lock | 50-69 |
| **`_cleanup_device()`** | force-stop TT/IG/YT + `logcat -c` | 71-100 |
| `_lock_portrait_orientation()` | settings put system user_rotation 0 | 102-112 |
| `_detect_android_user()` | `am get-current-user` → regex userid | 114-119 |
| `_ensure_yosemite_package()` | Yosemite.install_or_upgrade() | 121-124 |
| `_ensure_input_method()` | `ime set --user X yosemite/IME` | 126-141 |
| **`type_text(content)`** | `am broadcast -a ADB_INPUT_TEXT --es msg "..."` | 143-153 |
| **`tap(coords, image, record_pos, zone_percentage, threshold)`** | unified tap с image-matching + zone validation | 169-221 |
| `start_ig / start_tiktok / start_yt` | `start_app(pkg)` + `sleep 8` | 223-249 |
| `swipe_next_video(social_media)` | платформо-зависимая рандомизация swipe coords | 277-297 |
| `watch_search_results(video_count, watch_s, like_every, comment_every, comments)` | probability-based like/comment во время scroll | 299-341 |
| `open_search_results(social, keyword)` | платформо-зависимое открытие search | 343-380 |
| **`run_search_and_watch_flow(...)`** | full-flow: launcher + open_search + watch | 381-417 |
| `check_auth(social_media)` | проверка auth через image-templates (IG_CREATE_NEW_ACCOUNT, TIKTOK_SIGN_IN) | 449-471 |
| `humanize_like(social_media)` | per-platform coords (TT — image-based!) | 473-486 |
| `humanize_subscribe(social_media)` | per-platform coords | 488-496 |
| `humanize_comment(typing_text, social_media)` | полный flow с сохранением/закрытием | 498-562 |
| `humanize_favorite_video` | IG only | 564-572 |
| `humanize_profile_edit` | TT/IG | 574-604 |
| `humanize_create_story` / `humanize_publish_reels` | | 606-632 |
| **`close_social_media()`** | force-stop всех соцсетей | 633 |

## Сильные стороны (для нашего проекта)

### 1. **`_cleanup_device()` + `close_social_media()`** — форс-закрытие перед стартом

```python
def _cleanup_device(self):
    G.DEVICE.adb.shell("am kill-all")
    for app in ["com.zhiliaoapp.musically", "com.instagram.android",
                "com.google.android.youtube"]:
        G.DEVICE.adb.shell(f"am force-stop {app}")
    G.DEVICE.adb.shell("logcat -c")
```

**Ценность для нас:** прямое решение root-cause в T2 (account-read 3 retries × 5s fail потому что app в транзитном состоянии). Запустили → очистили → стартанули — UI предсказуемый.

### 2. **`tap(image=..., zone_percentage=...)`** — image-based tap с region validation

```python
def tap(self, coords=None, image=None, record_pos=None,
        zone_percentage=None, threshold=0.8, ...):
    # coords → touch(coords)
    # image → Template(image, record_pos, threshold=0.8)
    #        pos = exists(template)
    #        if zone_percentage:
    #            # check that pos is inside zone_percentage rect
    #        touch(pos)
```

**Ценность для нас:** когда XML regex не срабатывает (наш T2 случай с TikTok), image-match + zone-check **даёт 2-й независимый источник**. `zone_percentage` предотвращает ложные срабатывания (темплейт находится на wrong part of screen).

**Зависимость:** `airtest.core.api.Template` + `exists()` + `touch()`. Можно инкапсулировать и использовать выборочно — не рефакторить весь наш код.

### 3. **Yosemite IME для type_text**

```python
G.DEVICE.adb.shell(f'am broadcast -a ADB_INPUT_TEXT --es msg "{escaped}"')
```

Сравни с нашим подходом — вероятно используем `input text` ADB, который ломается на русском тексте и спецсимволах. Yosemite IME — проверенное решение для RU/non-ASCII.

**Ценность:** средняя, зависит от того, насколько стабильно работает наш текущий type_text.

### 4. **Celery + billiard timeout (T3 reuse-кандидат)**

```python
# celery.py
task_time_limit=60 * 40,           # hard (SIGKILL)
task_soft_time_limit=60 * 35,      # soft (SoftTimeLimitExceeded exception)
worker_max_tasks_per_child=2,       # recycle каждые 2 задачи
worker_max_memory_per_child=350,    # recycle при >350MB
```

```python
# worker.py
try:
    process.wait(timeout=60 * 40)
except SoftTimeLimitExceeded:
    logger.error("SoftTimeLimitExceeded — убиваем Airtest")
    process.kill()
    return -2
```

**Ценность:** **pattern (не код)** — внедрить эквивалент без Celery:
- `pid` колонка в autowarm_tasks
- scheduler.js делает `process.kill(pid, 'SIGTERM')` через 30-40 мин, `SIGKILL` через 45
- в Python-коде обработчик SIGTERM → cleanup-и + graceful exit
- worker_max_tasks_per_child эквивалент в pm2: `max_restarts` + `max_memory_restart`

### 5. **Декларативные daily modules**

```python
# ig/day1.py (22 строки)
def FirstDay(device_uri, subject=None, social_network="ig"):
    h = HumanizeActions(device_uri)
    h.close_social_media()
    keyword = subject or "trending"
    return h.run_search_and_watch_flow(
        social_network, keyword,
        video_count=15, watch_seconds=30, like_every=3, comment_every=5,
        comment_text="Nice video!",
    )
```

**Ценность:** наш `autowarm_protocols.days_config` jsonb — структурно аналог. Но у нас days_config — "что делать" (JSON), у них — реальный Python с параметрами. Можно унифицировать: day как Python-callable, параметры из DB.

## Слабые стороны (для нашего проекта)

1. **Целиком attached к Airtest** — нельзя вырвать `HumanizeActions` без `from airtest.core.api import *`. Нужно либо ставить Airtest (тяжеловесный, требует Java, поднятого uiautomator-helper), либо cherry-pick примитивы.

2. **Нет account-verification нигде.** Дэйли-модули предполагают «1 device = 1 account». У нас совсем другая модель (account_packages маппит до 3 платформ на device).

3. **Нет retry/recovery на уровне сценария.** Если `run_search_and_watch_flow` упал — Celery SoftTimeLimit его убьёт целиком. Наш warmer.py гораздо умнее в этом плане.

4. **`repositories/autowarm_tasks.py` минимальный** (15 строк) — update_status by `celery_task_id`. Ничего сложного для реюза.

5. **Docker-first** — их Dockerfile + pyproject.toml предполагают poetry + brightness конфиг Airtest. Развернуть рядом с нашим pm2 подходом — M-task, не S.

## Итог T6 (reuse-кандидаты с этого репо)

| Приоритет | Кандидат | Effort | Вырвать без Airtest? |
|---|---|---|---|
| **HIGH** | `_cleanup_device()` pattern — force-stop всех соцсетей перед account-verify | S (1 день) | **yes** (чистый ADB shell) |
| **HIGH** | Yosemite IME для type_text (если у нас есть проблемы с русским) | S-M | yes (`am broadcast ADB_INPUT_TEXT`) |
| MED | `tap(image=..., zone_percentage=...)` image-based tap | M | **no** — требует Airtest Template |
| MED | SoftTimeLimitExceeded pattern (через SIGTERM + handler в Python) | M | yes (адаптация) |
| MED | Декларативные daily modules вместо jsonb days_config | L | yes (но большой рефактор) |
| LOW | repositories DAO pattern (SQLAlchemy) | L | yes, но наш psycopg проще |

Главный кандидат: **`_cleanup_device()`** — одним 20-строчным helper'ом решает большую часть T2 root cause. Нулевая зависимость от Airtest.
