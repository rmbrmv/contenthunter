# WP #179 — unic-worker: `+faststart` на финальный mp4 (ручная выкладка IG/YT)

**Дата:** 2026-05-28
**Задача:** OpenProject #179 (Ошибка, «В спецификации», assignee Данил)
**Репозиторий кода:** `GenGo2/delivery-contenthunter` (testbench-чекаут `/home/claude-user/autowarm-testbench`, прод `/root/.openclaw/workspace-genri/autowarm`)
**Файл:** `unic-worker/worker.py`

## Контекст

`unic-worker` производит видео для пакета слотов уникализации (`unic_results.output_url`),
заливая итог в S3/CDN (`https://save.gengo.io/autowarm/unic/...`). Эти ссылки выдаются
делевери в разделе **«Выкладка»** (WP #107/#115/#123–#125) для **ручной выкладки**:
Данил скачивает файл на телефон и в IG-аппликухе делает «+ → Reels → выбрать видео».

**Симптом (2026-05-28 09:02 UTC, баг-репорт #2026-05-28T090243Z).** Свежие
unic-результаты для проекта `ClickPay` (id=85, аккаунт `clickpay_world`) в галерее
устройства отображаются с **чёрными миниатюрами**; **тап выбора не отрабатывает**
в IG (и частично в YT-creator-studio). Соседние «старые опубликованные» файлы из того
же источника — выбираются нормально.

**Корень (подтверждён по коду + ffprobe).** ffprobe + atom-walk трёх свежих файлов
`t3788/t3789` от 2026-05-26:

```
head bytes:  [ftyp(32), free(8), mdat(~21MB)]
moov atom: → в хвосте файла (после mdat)
```

`unic-worker/worker.py` финальный concat (`worker.py:322`):

```python
subprocess.run(
    ['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy',op],
    check=True, capture_output=True, timeout=120
)
```

— **не передаёт** `-movflags +faststart`. ffmpeg по умолчанию пишет moov в конец, чтобы
сначала собрать stbl/stco. Мобильные галереи (Android MediaStore / IG / YT mobile)
при построении миниатюры читают только первые ~1–2MB файла и **ищут moov upfront**;
не находят → выдают чёрный thumb. Без декодированного первого кадра выбор файла в
галерее IG не отрабатывает (это давно известный паттерн).

**Почему регресс не виден в авто-публикации.** В коде уже есть рабочий remux:
`publisher_base.py:2789` `_remux_mp4_if_available` и `screen_recorder.py:293,308`
делают `ffmpeg -c copy -movflags +faststart` перед загрузкой в IG-аппликуху.
Авто-публикатор всегда remux'ит свой output → IG нормально публикует. Ручная
выкладка отдаёт **прямую ссылку на CDN**, минуя публикатор → файл попадает на устройство
«сырым».

**Verified локально (2026-05-28):**
ручной `ffmpeg -c copy -movflags +faststart` на одном из файлов:

```
head bytes (after):  [ftyp(32), moov(34395)]
```

— moov в начале, без потери качества (только реорганизация атомов).

## Цель

1. Добавить `-movflags +faststart` в финальный output `unic-worker` — все новые `unic_results`
   автоматически попадают на CDN faststart-ready.
2. Бэкфилл существующих файлов через одноразовый remux на CDN — разблокировать ручную
   выкладку Данила сегодня (clickpay 26.05, ~30 файлов).
3. Тест-канарейка: положение `moov` в head после `create_final_output`.

**Out of scope (бэклог):**
- Нормализация разрешения под 1080×1920 (сейчас 1670×2790, 1640×2760 — не 9:16). Не
  блокирует ручную выкладку после faststart; вторичный фактор. Отдельная задача.
- H.264 Level 5.0 даунгрейд (auto-pub живёт с этим).
- Бот `contenthunter_bugs_bot` ловить `TelegramBadRequest: file is too big`
  (бот падает в `bot.py:135`, видео Данила не дошло). Отдельный бэклог.

## Решения (утверждены Данилом 2026-05-28)

- **Путь:** спека + план по WP (а не quick hotfix).
- **Фикс в коде:** только финальный concat (`worker.py:322`). `generate_ffmpeg`
  (промежуточный proc) трогать не нужно — final-concat через `-c copy` всё равно
  пересобирает структуру; faststart-флаг на финале достаточен.
- **Бэкфилл:** отдельный одноразовый скрипт; remux всех `unic_results` без faststart,
  у которых файл всё ещё в S3 и они не помечены как опубликованные. Безопасно
  (только заголовок).

## Дизайн

### 1. Фикс в `worker.py:322`

Было:

```python
subprocess.run(
    ['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy',op],
    check=True, capture_output=True, timeout=120
)
```

Будет:

```python
subprocess.run(
    ['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy',
     '-movflags','+faststart',op],
    check=True, capture_output=True, timeout=120
)
```

`-c copy` + `-movflags +faststart` — стандартная пара, ffmpeg пишет временный файл и
переставляет moov в начало (overhead ≈ один лишний рерайт ~20MB на устройстве
рабочей машины). Никакой потери качества. Тот же рецепт уже использован в
`publisher_base.py:2799` и `screen_recorder.py:293,308`.

**Kill-switch не требуется.** Изменение чистое (атомы переставлены, контент идентичен).
Авто-публикатор продолжает работать (его собственный remux — no-op на уже-faststart файле,
`_remux_mp4_if_available` идемпотентен).

### 2. Тест-канарейка

Новый файл `unic-worker/tests/test_create_final_output_faststart.py`:

- Хелпер `atom_offsets(path)` — читает первые 4KB, возвращает `{name: offset}` верхнеуровневых
  атомов через ISOBMFF box walk (зеркало того, что мы делали в разведке 28.05).
- Сид: `ffmpeg -f lavfi -i color=c=red:s=320x320:d=1 -c:v libx264 -pix_fmt yuv420p
  -f lavfi -i anullsrc -shortest seed.mp4` (1сек красный квадрат с тишиной).
- Вызов `create_final_output(seed, scheme_id=0, base_name='test_ff')`.
- Assert: `atom_offsets(out)['moov'] < atom_offsets(out)['mdat']`.
- Regression-канарейка: если кто-то в будущем уберёт `-movflags +faststart` — тест падает.

Тест **interaction-light** (использует реальный ffmpeg/ffprobe, есть в окружении). На testbench
проходит за <2s.

### 3. Бэкфилл существующих `unic_results`

Отдельный одноразовый скрипт `unic-worker/scripts/backfill_faststart.py`:

- SELECT из БД: `unic_results.output_url` где `status='done'`, файл всё ещё в S3,
  и **либо** этот результат не помечен как opublik'ован (нет `publish_queue.unic_result_id`
  c status='published'), **либо** он привязан к manual-публикации (`validator_manual_publish_queue`).
- Опциональный фильтр `--project-id 85` для первого прогона (только clickpay, 30 файлов).
- Для каждого: head-fetch 4KB → atom-walk → если moov в head, **skip**; иначе:
  download → `ffmpeg -c copy -movflags +faststart` → upload поверх той же ключа.
- Идемпотентно (повторный прогон skip'ает уже-faststart).
- `--dry-run` для смока.

**Откат бэкфилла.** Перед каждой перезаливкой сохраняем оригинал на CDN под суффиксом
`.preremux.mp4` на 24ч (cron-cleanup). При проблеме — `s3 cp pre→main`.

### 4. Observability

Простое INFO-логирование в worker: после `subprocess.run` концата — один лог
`unic.final.faststart path=... size=... atom0=moov` (через head-walk выходного файла).
Это не critical, но в проде даст подтверждение что фикс активен (грепабельно по
`unic.final.faststart`).

## Тесты (TDD)

Phase 1 — failing test:

1. `tests/test_create_final_output_faststart.py::test_moov_before_mdat` — без правки
   `worker.py:322` тест **должен падать**. Это доказывает, что тест чувствительный.

Phase 2 — green:

2. Применяем правку → тот же тест зелёный.

Phase 3 — backfill smoke:

3. `tests/test_backfill_faststart.py::test_skip_already_faststart` — мокаем S3, проверяем что
   уже-faststart файл скрипт не трогает.
4. `tests/test_backfill_faststart.py::test_remux_non_faststart` — для файла с moov-в-хвосте
   скрипт делает remux и аплоадит.

## Выкатка и верификация

1. PR в `GenGo2/delivery-contenthunter` main → прод `git pull`. **Рестарт unic-worker:**
   `pm2 restart unic-worker` (testbench и прод). Без рестарта старые воркер-инстансы
   продолжат рендерить без faststart.
2. **Live-smoke**: вручную создать `unic_tasks` запись для clickpay (или взять live
   slot) → дождаться `done` → ffprobe → проверить atom-order на новом файле.
3. **Backfill clickpay 26.05** через `--project-id 85 --dry-run`, потом без dry-run.
   Подтверждение: head-fetch 4KB любого из 30 файлов → moov в head.
4. **User-verify**: Данил повторно скачивает файл из раздела «Выкладка» делевери, в IG
   галерее — миниатюра строится, выбор работает, публикуется.
5. **Бэкфилл «широкий»** (все active unic_results без faststart) — после успешного
   ClickPay-смока; ограничить по дате (не трогаем уже-published давно файлы; см. фильтр).

## Откат

- **Код:** revert PR (одна правка, безопасно).
- **Бэкфилл:** перезалив `*.preremux.mp4` → основной key (через `aws s3 cp`).

## Acceptance

- [ ] `worker.py:322` концат с `-movflags +faststart`.
- [ ] `test_create_final_output_faststart.py` зелёный; без фикса — красный.
- [ ] `backfill_faststart.py` идемпотентен, dry-run покажет N кандидатов.
- [ ] После backfill 30 файлов clickpay 26.05 — все с `moov` в head.
- [ ] Данил подтверждает ручную выкладку Reels из клипа clickpay.
- [ ] Авто-публикация IG не деградирует (success-rate не упал).

## Бэклоги (отдельные WP)

- Бот `contenthunter_bugs_bot` — поймать `TelegramBadRequest: file is too big` в
  `bot.py:135`, ответить «пришли ссылку Yandex Disk», вписать `media: failed` в md.
- Нормализация разрешения unic-схем под 9:16 (1080×1920 / 1080×1080) — устранит
  «вторичный» фактор; долгосрочно полезно для качества миниатюр и единообразия.
