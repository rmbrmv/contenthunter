# WP #185 — unic-worker финальный transcode в 1080×1920 (Main/4.1/faststart)

**Дата:** 2026-05-28
**Задача:** OpenProject #185 (Ошибка, «В спецификации», assignee Данил)
**Родитель:** [WP #179](/work_packages/179) (faststart-фикс — был необходим, но недостаточен)
**Репозиторий кода:** `GenGo2/delivery-contenthunter` (прод `/root/.openclaw/workspace-genri/autowarm`)
**Файл:** `unic-worker/worker.py` (`create_final_output`, l.313–360 после WP #179) + `unic-worker/scripts/backfill_faststart.py`

## Контекст

[WP #179](/work_packages/179) SHIPPED+DEPLOYED 28.05 — `worker.py:322` добавил
`-movflags +faststart`, бэкфилл `clickpay 26.05` (32) + active manual queue (154) + превентивный
(~1009 in progress) выровнял `moov` atom в head. Это закрыло «чёрные миниатюры» для большой
части файлов.

**Однако** 28.05 ~17:30 МСК Данил протестировал бэкфиллнутый
`https://save.gengo.io/autowarm/unic/20260523190825_t3716_4a7a507c_s4.mp4` на телефоне №19
(Samsung SM-A175F). Скриншоты:

- Файловый менеджер: иконка-плейсхолдер (не миниатюра), фиолетовый кружок play.
- Системный плеер: чёрный экран + сообщение **«Невозможно воспроизвести видео.
  Не поддерживается видеокодек.»**.
- IG-галерея Reels: файла **просто нет** в списке «Недавние» (соседние видео есть).

Параметры файла на CDN:

```
H.264 High @ Level 5.0
1570×2690 (нестандарт, не 9:16, не 1080×1920)
yuv420p, 30 fps
bit_rate 7.7 Mbps, duration 38.6с, size 38.4 MB
faststart: ✓ ([ftyp(32), moov(43225)])
```

Старый файл 14.05 (по словам Данила выкладывался нормально) — `20260514172225_t2285_864636ba_s30.mp4`:

```
H.264 High @ Level 5.0
1560×2680 (тоже нестандарт, ±10 пикселей от broken-файла)
yuv420p, 30 fps
bit_rate 5.9 Mbps, duration 23.6с
```

**Параметры почти идентичны**, но старый работает, новый — нет. Корень не в Level 5.0 как
таковом, а в специфике bitstream. **Различие в схемах уникализации:**

- Схема #4 (broken): `scale_add=230`, `pad_add=330`, `rotate=-2.15°`, `crop_reduce=430`, `speed=1.20×`
- Схема #30 (working): `scale_add=140`, `pad_add=240`, `rotate=+1.10°`, `crop_reduce=260`, `speed=1.07×`

То есть HW-decoder Samsung A17 фейлит на агрессивно-уникализированных файлах. Не каждая
схема ломает, но угадать заранее нельзя.

**Verified-fix:** transcoded версия (Main/Level 4.1/1080×1850 через scale=1080:-2/4 Mbps/faststart)
загружена на CDN как `…s4.transcoded_test.mp4`. Данил подтвердил (28.05 17:42–17:46 МСК):

- Файловый менеджер: миниатюра «молодой» (превью первого кадра).
- Системный плеер: воспроизводит (видна полоса прогресса 0:10/0:38).
- IG-галерея Reels: файл виден сверху списка «Недавние» (0:39).
- Reels picker: выбирается, появляется превью + «Редактировать видео» / «Далее».

## Цель

1. Заменить финальный `-c copy +faststart` в `unic-worker` на **lossy safety-transcode**
   с гарантированно mobile-safe параметрами (Main/Level 4.1/1080×1920/faststart).
2. Бэкфилл существующих файлов через тот же transcode (новый флаг `--transcode`).
3. Тест-канарейка на параметры выхода (width=1080, height=1920, profile=Main, level=41).
4. Сохранить наследие WP #179 — observability `unic.final.faststart_ok` остаётся; добавляем
   `unic.final.transcode_ok` подобную (или расширяем существующий).

**Out of scope:**

- НЕ меняем схемы уникализации (`scale_add`/`pad_add` остаются — применяются к промежуточному
  `processed_path`, который потом скейлится в финале).
- НЕ меняем автоматический публикатор — он работал и работает.
- НЕ удаляем `.preremux.mp4` бэкапы (cleanup_preremux запускается отдельно T+24ч).
- Hardware acceleration (NVENC) — opt-in отдельной задачей, если transcode станет узким местом.

## Решения (утверждены Данилом 2026-05-28)

- **Целевой размер**: 1080×1920 строго (стандарт IG Reels).
- **Aspect handling**: pad (scale-to-fit + чёрные полосы по краям). Ничего не теряется.
- **Куда воткнуть**: в unic-worker `create_final_output` (каждый новый файл).
- **Trade-off uniqueness**: размер всегда одинаков; uniqueness живёт в content-уровне
  (rotate, speed, crop_offset, overlays, color shifts). Согласовано.

## Дизайн

### 1. Финальный transcode в `worker.py:322`

Сейчас (после WP #179):

```python
subprocess.run(
    ['ffmpeg','-y','-f','concat','-safe','0','-i',cp,
     '-c','copy','-movflags','+faststart',op],
    check=True, capture_output=True, timeout=120,
)
```

Будет:

```python
subprocess.run(
    ['ffmpeg','-y','-f','concat','-safe','0','-i',cp,
     '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,'
            'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30',
     '-c:v','libx264','-profile:v','main','-level','4.1',
     '-preset','medium','-crf','23',
     '-c:a','aac','-b:a','128k',
     '-movflags','+faststart',
     op],
    check=True, capture_output=True, timeout=300,
)
```

- `scale=1080:1920:force_original_aspect_ratio=decrease` — масштабирует так, чтобы вписаться
  в 1080×1920 без выхода за края (одна сторона будет меньше).
- `pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black` — добивает чёрными полосами до 1080×1920.
- `fps=30` — нормализация (защита от нестандартного fps).
- `profile=main level=4.1` — гарантированно поддерживается всеми Android Lollipop+ и iOS 11+.
- `preset=medium crf=23` — баланс размер/скорость/качество, выход <5 Mbps для 9:16 30fps.
- timeout 120→300с — медленнее concat'а, нужен запас (~30-40с на файл 30-60с длительности).

### 2. Observability — `unic.final.transcode_ok`

После concat-transcode в `create_final_output` (расширяем существующий блок WP #179):

```python
try:
    with open(op, "rb") as _fh:
        _head = _fh.read(1024 * 1024)
    _i = 0
    _moov_off = _mdat_off = None
    while _i + 8 <= len(_head):
        _sz = struct.unpack(">I", _head[_i:_i+4])[0]
        _name = _head[_i+4:_i+8].decode("ascii", errors="replace")
        if not _name.isalnum():
            break
        if _name == "moov" and _moov_off is None:
            _moov_off = _i
        if _name == "mdat" and _mdat_off is None:
            _mdat_off = _i
        if _sz < 8:
            break
        _i += _sz
    _faststart_ok = (_moov_off is not None) and (_mdat_off is None or _moov_off < _mdat_off)
    # доп. проверка параметров — реальные width/height/profile/level
    import subprocess as _sp
    _probe = _sp.run(
        ['ffprobe','-v','error','-select_streams','v:0',
         '-show_entries','stream=width,height,profile,level',
         '-of','default=nw=1', op],
        capture_output=True, text=True, timeout=15,
    ).stdout
    _params_ok = ('width=1080' in _probe and 'height=1920' in _probe
                  and 'profile=Main' in _probe and 'level=41' in _probe)
    if _faststart_ok and _params_ok:
        logger.info(
            f"unic.final.transcode_ok scheme_id={scheme_id} size={os.path.getsize(op)} "
            f"moov_off={_moov_off} mdat_off={_mdat_off}"
        )
    else:
        logger.warning(
            f"unic.final.transcode_DEVIANT scheme_id={scheme_id} "
            f"faststart={_faststart_ok} params={_params_ok} probe={_probe.replace(chr(10),' ')}"
        )
except Exception as _e:
    logger.warning(f"unic.final.transcode_check_failed scheme_id={scheme_id} err={_e}")
```

### 3. Бэкфилл-режим `--transcode`

Существующий `scripts/backfill_faststart.py` расширяется:

- Новый флаг `--transcode` (бок-о-бок с `--queue-only`, `--project-id`, `--since`).
- При `--transcode`:
  - `head_has_moov` → `is_already_mobile_safe`: проверяет moov-в-head **И** params (width=1080,
    height=1920, profile=Main, level=41). Если всё ОК → skip.
  - `remux_to_faststart` → `transcode_to_mobile_safe`: тот же ffmpeg-вызов что в worker.py.
  - Всё остальное (download → backup → upload) остаётся.
- Без `--transcode` — старое поведение (только remux+faststart).

`is_already_mobile_safe` использует `head_object` для извлечения `Metadata` (если бэкфилл-скрипт
помечает успешные transcoded файлы тегом `wp185_transcoded=1`) — иначе full ffprobe download
+ check.

Backup-key для transcode: `<key>.pretranscode.mp4` (отдельный от `.preremux.mp4` чтобы
cleanup'ы не путались). Tagging `wp185_pretranscode=1`.

### 4. Тесты (TDD)

- `test_create_final_output_faststart.py` (WP #179) **расширяется**: после трансформации
  проверять не только `moov<mdat`, но и `width=1080`, `height=1920`, `profile=Main`, `level=41`.
- `test_backfill_faststart.py` **расширяется**:
  - `is_already_mobile_safe` true когда tag wp185_transcoded=1
  - `is_already_mobile_safe` true когда params via ffprobe match
  - `is_already_mobile_safe` false когда params devianted
  - `process_one(..., transcode=True)` использует transcode вместо remux
- Новый smoke-тест канарейки: рендер тестового seed → output точно 1080×1920 Main/41.

### 5. Бэкфилл-runbook

```bash
# 1. Очередь ручной выкладки (priority): ~154 файла, ~1.5ч
python -m scripts.backfill_faststart --queue-only --transcode --dry-run
python -m scripts.backfill_faststart --queue-only --transcode

# 2. Превентивный pool последней недели (фон): ~1000 файлов, ~10ч
nohup python -m scripts.backfill_faststart --since 2026-05-21 --transcode > /tmp/backfill_transcode.log 2>&1 &
```

(Текущий превентивный --since 2026-05-21 faststart-only пускай **завершится** — он не помешает,
автоматический публикатор использует remux на стороне публикатора и от него получает faststart-ok
файлы.)

## Тесты-канарейки (TDD)

Phase 1 — failing:

1. `test_create_final_output_faststart.py::test_output_is_1080x1920_main_4_1` (расширение
   существующего теста): после `create_final_output(seed)` — `ffprobe` показывает width=1080,
   height=1920, profile=Main, level=41. До правки worker.py — падает (старый рендер High/5.0).

Phase 2 — green:

2. Применяем правку → тест проходит.

Phase 3 — backfill:

3. `test_backfill_faststart.py::test_process_one_transcode_mode` (новый): mock S3,
   `process_one(s3, row, dry_run=False, transcode=True)` вызывает `transcode_to_mobile_safe`,
   не `remux_to_faststart`.
4. `test_backfill_faststart.py::test_is_already_mobile_safe_via_tag`: если в head_object Metadata
   тег wp185_transcoded=1 → skip без полного download.

## Выкатка и верификация

1. PR в `GenGo2/delivery-contenthunter` → merge → прод `git pull` → `sudo pm2 restart unic-worker`.
2. **Live-smoke**: новый unic_result (живой или ad-hoc trigger) → ffprobe выходного файла →
   width=1080 height=1920 profile=Main level=41 + faststart-ok + грепабельный лог
   `unic.final.transcode_ok`.
3. **Backfill очереди** (`--queue-only --transcode`): ~154 → проверить два-три случайных файла
   через ffprobe (включая агрессивные схемы #4/#25/#28-30).
4. **User-verify**: Данил повторно скачивает любое clickpay/feminista/ambassadori из «Выкладки» →
   IG-галерея показывает миниатюру + выбор в Reels picker работает.
5. **Превентивный backfill** (`--since 2026-05-21 --transcode`) — фоном на ~10ч (или ночью).
6. OpenProject #185 → «Тестирование».

## Откат

- Код: revert PR (одна функция в `worker.py` + добавление флага в backfill).
- Backfill: восстановление через `*.pretranscode.mp4` бэкап-копии.

## Acceptance

- [ ] `worker.py:322` концат+transcode с целевыми параметрами.
- [ ] `test_create_final_output_faststart.py` зелёный для расширенных проверок (width/height/profile/level).
- [ ] `unic.final.transcode_ok` / `unic.final.transcode_DEVIANT` в прод-логах.
- [ ] Backfill --queue-only --transcode: 154/154 → params=ok, faststart=ok.
- [ ] Данил подтверждает ручную выкладку Reels для clickpay 23.05 (s4) и одного другого проекта.
- [ ] Авто-публикация IG не деградирует (success-rate не упал; transcode на стороне публикатора
      идемпотентен с уже-mobile-safe файлом).

## Бэклог (отдельные WP)

- Hardware-accel transcode (h264_nvenc / VAAPI) — если CPU transcode станет bottleneck'ом.
- Бот `contenthunter_bugs_bot` — поймать `TelegramBadRequest: file is too big`.
- Audit «достаточно ли Level 4.1» — проверить на iOS 11+ устройствах (Safari, Photos, IG).
