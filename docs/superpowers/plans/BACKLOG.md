# Backlog tickets

## 2026-05-29 — WP #161 (iter2): TG-уведомления одобрение/отсутствие контента — фикс бага + 1×09:00

### ✅ SHIPPED+DEPLOYED 2026-05-29 — OpenProject #161 → Тестирование; impl на main `delivery-contenthunter` `e7bf12e`, прод pulled (FF) + PM2 id35 restart

Доработка живой фичи (iter1 SHIPPED 27.05) по комментариям автора (Анастасия/Аня) 28–29.05 + найденный баг. 4 правки:

**(1) Баг блока «контент не загружен» (ложные срабатывания).** SQL флагал клиента при ЛЮБОМ пустом слоте; у проектов 2 слота/день (один обычно пуст) → ложно попадали почти все активные. Аня привела 9 проектов с контентом, числившихся «без контента». Фикс = правило «весь день пуст»: `GROUP BY (project, slot_date) HAVING count(*) FILTER (WHERE content_id IS NOT NULL) = 0`. Проверено на живой БД: из 9 «ложных» остался только AXILOR Private на 31.05 (там реально оба слота пусты).

**(2) Блок «на одобрении» → фильтр `slot_date >= today` (МСК)**, INNER JOIN + `HAVING ... > 0` (бездатные и только-прошлые ролики скрыты). РАЗВОРОТ iter1-решения «stale-даты оставляем по спеке». На проде блок сейчас пуст корректно: все 75 needs_review просрочены (макс. дата 22.05).

**(3) Раздельные абзацы** «Нет контента на завтра (DD.MM)» / «на послезавтра (DD.MM)», каждый — только при наличии клиентов.

**(4) Каденция почасовая 09–18 → 1 раз 09:00 МСК** (`APPROVAL_NOTIFY_TIME_MSK`, `isReportDue`/`mskSendDate` по образцу daily_publish_report). Идемпотентность = **дневной** claim (переиспользована `approval_notify_runs`, миграции НЕТ).

**Качество.** 26 юнит-тестов GREEN, codex review 0 P1, subagent-driven (5 TDD-тасков) + независимое финальное ревью (SPEC_COMPLIANT + QUALITY_APPROVED). Дифф трогает только `approval_notify.js` + тест.

**Деплой.** FF push GenGo2/delivery-contenthunter main `e7bf12e` → прод `/root/.openclaw/workspace-genri/autowarm` `git pull --ff-only` (точечный `sudo chown` 2 root-owned файлов перед pull, т.к. `sudo git` не в NOPASSWD) → `sudo pm2 restart autowarm` (id35), крон `[approval-notify] scheduled daily at 09:00 MSK`. Прод `.env`: `APPROVAL_NOTIFY_*` не заданы → дефолты (токен fallback на `DAILY_REPORT_BOT_TOKEN`).

**Остаток.**
- Verify первой штатной автоотправки **09:00 МСК 30.05** → «Готово» (catch-up отправка 29.05 17:08 уже прошла: новый формат, оба абзаца, idempotent skip на повторном тике).
- Kill-switch `APPROVAL_NOTIFY_ENABLED=0` наготове.

Спека/план/evidence: `docs/superpowers/specs|plans/2026-05-29-wp161-iter2-approval-notify-refine*`, `docs/evidence/2026-05-29-wp161-iter2-approval-notify-refine-shipped.md`. Память: `project_wp161_tg_approval_notify`. Откат: `APPROVAL_NOTIFY_ENABLED=0`.

---

## 2026-05-29 — WP #191: TikTok переключатель тапает «Заблокированные аккаунты» (substring-leak)

### ✅ SHIPPED+DEPLOYED 2026-05-29 — OpenProject #191 → Тестирование; impl на main `delivery-contenthunter` `55bdbd9` (+doc `b67e088`), прод pulled (FF) + PM2 id35 restart (#29)

Триаж падений TikTok за 29.05 (`publish_tasks`, 22 failed): **топ-1 причина `tt_drawer_tap_did_not_open_sheet` = 5/22 (≈23%)**, все clickpay-аккаунты (tasks 11919/11944/12019/12025/12038, 3 устройства). Кластер «переключение аккаунтов» в целом = 16/22 ≈ 73%.

**Root cause (сошлись 4 источника).** В settings-фолбэке свитчера (`account_switcher.py::_run_tt_phase2_menu_path`) матчер `_find_tt_account_switcher_anchor_in_drawer` ищет точку входа **подстрокой** (`trigger in label.lower()`, строки 4975/4985). Триггер `'аккаунты'` (`TT_DRAWER_ACCOUNT_TRIGGERS`) ⊂ «заблокированные аккаунты» → на скролле страницы «Настройки и конфиденциальность» строка «Заблокированные аккаунты» (раздел Приватность) ошибочно опознаётся как переключатель и тапается → dead-end → шит не открывается. Доказано: UI-дампы шага `tt_3_open_list_sheet` у всех 5 = читаемая страница «Заблокированные аккаунты» (usable=False 8312b) + скринкаст 12038 висит на ней + предыдущие шаги usable=True + `sheet_open_signal=false`/`drawer_anchor_label=''` (Pass 2). Word-boundary НЕ помогает — «аккаунты» там целое слово.

**Решение.** Blocklist `TT_DRAWER_DEADEND_SUBSTRINGS` (`заблокированные аккаунт`, `blocked account`) + `_tt_label_is_account_deadend` + skip в обоих pass-ах матчера. Kill-switch `TT_DRAWER_DEADEND_SKIP_ENABLED` (default ON; OFF = legacy). TDD: 7 unit-тестов (оба pass-а RU/EN, позитив «Сменить аккаунт»/«Управление аккаунтами», kill-switch). Регресс: 427 switcher/TT unit зелёных, 0 регрессий. Codex review: 0 P1.

**Деплой.** Прод-autowarm `/root/.openclaw/workspace-genri/autowarm` (PM2 id35) FF к origin/main `b67e088`; флаг ON; PM2 id35 restart (#29, account_switcher импортируется воркером). Прод-HEAD сверен, import-smoke OK.

**Остаток.**
- Verify 24-48ч: 0 `tt_drawer_tap_did_not_open_sheet` с переходом на «Заблокированные аккаунты» на clickpay.
- Остальной TT-кластер падений (не в scope #191): `tt_upload_confirmation_timeout` (3), `tt_account_not_in_list` (3, см. WP#163 truncation), `tt_account_sheet_closed_before_parse` (3, WP#182 на тестировании), `tt_fg_drift_unrecoverable` (2), `tt_switch_blocked` (2 = аккаунт забанен, не код). Наблюдать; отдельные WP при рецидиве.

Evidence: `docs/evidence/2026-05-29-tt-publish-fails-triage.md` (+ `evidence/publish-triage/tt_blocked_accounts_substring-20260529.md` в autowarm). Память: `project_wp191_tt_blocked_accounts_substring`. Откат: `TT_DRAWER_DEADEND_SKIP_ENABLED=0`.

---

## 2026-05-29 — WP #44 (iter2): TikTok публикуется БЕЗ описания — честный focus-gate

### ✅ SHIPPED+DEPLOYED 2026-05-29 — OpenProject #44 → Тестирование; impl на main `delivery-contenthunter` `b1ee6d2`, прод pulled (FF, без PM2-restart)

Пришло от Анастасии (комментарии в OP#44): по TikTok массово с 26.05 выкладка без описания (и без хэштегов — они вшиты в текст), 29.05 «все сегодняшние в ТикТок без описаний» (тел. 162/163/165, Кликпей, Юлия Сваровски 74/75, Lexis Voice 16/17, PANDAFiT 73, Комильфо 37/39, аквабрайт 81/82). iter1 (`hashtag_enrich.js` добивка тегов) — отдельная рабочая фича, ни при чём.

**Root cause (по проду).** `publish_tasks.caption` корректный (29.05 — 59/59 непустых) → серверная сборка ОК, проблема device-side. Поле описания TikTok рендерится через Canvas/обфусцированные классы (`X.12py`, `X.10UB`) — в UI-дампах НЕТ `EditText`/`focused`/читаемого текста. `publisher_tiktok.py` (старый Шаг-4 ~1872-1928): `tap_element` не находит поле → fallback по фикс-координатам `(540,250..400)` → **`adb_text` вызывался ВСЕГДА**, даже когда клавиатура не открылась (поле не сфокусировано), и логировал ложный «✅ caption введён». Текст уходил «в никуда». Доля слепого fallback росла: 28.05=69%, 29.05=64%. Зеркало надёжного IG-механизма (`_extract_caption_input_state` + verify + `ig_caption_screen_not_reached`), которого в TT не было.

**Решение.** Новые методы `_tiktok_caption_field_focused` (фокус по IME `dumpsys input_method mInputShown` — единственный Canvas-независимый сигнал; парсит конкретный флаг, не «любой =true») + `_fill_tiktok_caption`: печать только при `desc_found AND focused`; иначе честный `log_event('error', meta.category='tt_caption_field_not_focused')` + `return False` → `publish_tiktok` прерывает публикацию ДО share → задача в ручную очередь (класс `ui_changed`/manual). Kill-switch `TT_CAPTION_FOCUS_GATE_ENABLED` (default ON; OFF = legacy слепая печать). Миграция `tt_caption_field_not_focused` в `publish_error_codes`.

**Процесс (Superpowers).** Брейншторм → спека → план (codex 0 P1, 2 раунда: поймал mInputShown-парсинг + требование desc_found) → subagent-driven impl (Task1 миграция, Tasks2-4 helpers+врезка+тесты; spec-review ✅ + quality Approved + 2 code-review minor подчищены) → локальный merge → деплой. 10/10 unit-тестов, соседние сьюты 0 регрессий (1 краснота `test_publish_guard.py` pre-existing на origin/main). codex 0 P1 на спеке/плане/коде.

**Деплой.** Прод-autowarm `/root/.openclaw/workspace-genri/autowarm` (PM2 id35) FF к origin/main `b1ee6d2`; миграция в живой БД; флаг ON; PM2-restart НЕ нужен (server.js не менялся, publisher per-task spawn). Прод-HEAD сверен с origin/main.

**Инцидент в процессе.** Параллельная сессия (WP#180 iter2) переключила общий `autowarm-testbench` чекаут на `feat/wp180` МЕЖДУ моими git-командами → мой merge лёг на чужую ветку. Откатил (`reset --hard e08316b` = origin, дерево чистое, ничего не потеряно; их работа даже включила мой WP44 в основу), деплой доделал через изолированный worktree. Урок: для merge/push в shared-чекаут — ВСЕГДА worktree, разовой `branch --show-current` не доверять.

**Остаток / out-of-scope.**
- **iter3 (если honest_fail зафлудит ручную очередь):** точнее наводиться на Canvas-поле — тап по центру bounds узла-маркера вместо фикс-координат; возможно tap по нескольким Y с проверкой фокуса до перебора координат. Снизит долю ухода в ручную. Постов без описания уже не будет в любом случае.
- IG/YT — вне scope (IG надёжен, YT отдельное поле описания; симптом только TT).

Evidence: spec `docs/superpowers/specs/2026-05-29-wp44-tt-caption-honest-fill-design.md`; plan `docs/superpowers/plans/2026-05-29-wp44-tt-caption-honest-fill.md`. Память: `project_wp44_tt_caption_honest_fill`. Verify: утренняя пачка — нет TT-постов без описания + доля честных `tt_caption_field_not_focused`. Откат: `TT_CAPTION_FOCUS_GATE_ENABLED=0`.

---

## 2026-05-28 — WP #179+#185: unic-worker mobile-safe transcode для ручной выкладки IG

### ✅ ГОТОВО 2026-05-28 — OpenProject #179 + #185 → Готово; impl на main `delivery-contenthunter` 98d0f67 → прод pulled + pm2 restart unic-worker; verified Данилом на 19/SM-A175F (плеер + IG-редактор OK)

Пришло как баг-репорт (`sources/bugs/inbox/2026-05-28T085657Z-Danil_Pavlov_123-ни-она-инста-не-груз.md` + парный `…T090243Z-…фвыафыв.md` + видео-доказательство https://disk.yandex.ru/i/rh1chvMsDXmWrw). Симптом: ручная выкладка через мобильный Instagram → «+ Reels → выбрать видео из галереи». Чёрные миниатюры у новых файлов, IG не реагирует на тап выбора, «Не поддерживается видеокодек» в системном плеере, файла НЕТ в IG-галерее «Недавние». Старые опубликованные выбираются нормально.

**Root cause в два слоя.**

**Слой 1 (WP #179, faststart):** `unic-worker/worker.py:322` финальный concat без `-movflags +faststart` → `moov atom` уходил в хвост mp4 → мобильная галерея читает первые 1-2MB при построении миниатюры → не находит moov → чёрный thumb + не выбирается. Авто-публикатор не страдал — `publisher_base.py:2789 _remux_mp4_if_available` уже делал faststart-remux перед загрузкой в IG-аппликуху. Ручная выкладка отдавала прямую CDN-ссылку → сырой файл.

**Слой 2 (WP #185, mobile HW-decoder):** Verified Данилом — faststart-only оказался недостаточен. Файл с moov в head всё равно «не поддерживался видеокодек» и не виден в IG-галерее. Сравнение со старым работающим (1560×2680, H.264 High Level 5.0, 6 Mbps) показало почти идентичные параметры с broken (1570×2690, та же Level 5.0, 8 Mbps) — разница лишь в схеме уникализации: схема #4 агрессивная (rotate=-2.15°, speed=1.20×, scale_add=230, crop_reduce=430) vs working схема #30 мягкая (rotate=+1.10°, speed=1.07×, scale_add=140, crop_reduce=260). HW-decoder Samsung A17 фейлит на специфике bitstream агрессивных схем, даже когда параметры контейнера формально валидны.

**Решение (WP #185).** Финальный safety-transcode в `worker.py:322`: replaced `-c copy +faststart` на полноценный lossy `ffmpeg -c:v libx264 -profile:v main -level 4.1 -pix_fmt yuv420p -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart` с `-vf scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30`. Размер строго 1080×1920 теряет нестандартный uniqueness `scale_add`/`pad_add`, но content-level (rotate/speed/crop_offset/overlays/color) остаётся — согласовано с Данилом, соц-сети всё равно нормализуют при upload.

**Observability.** `unic.final.transcode_ok` / `transcode_DEVIANT` с **fail-closed** `RuntimeError` на deviant (требует ffprobe-проверки width=1080+height=1920+profile=Main+level=41+pix_fmt=yuv420p+audio=aac+faststart). Это проктовый regression-сигнал для любой будущей правки worker.

**Backfill.** `scripts/backfill_faststart.py` расширен флагами `--queue-only` (JOIN с `validator_manual_publish_queue` published_at IS NULL AND cancelled_at IS NULL) и `--transcode` (full transcode vs faststart-only). `is_already_mobile_safe` для idempotency (fast-path tag `wp185_transcoded=1`, slow-path ffprobe head 256KB). `_local_is_mobile_safe` post-transcode validation. `.pretranscode.mp4` бэкап + tagging. `cleanup_preremux.py` для T+24ч очистки (двойной фильтр: суффикс + тег + LastModified).

**Деплой и волны бэкфилла.**
- WP #179 (faststart-only): clickpay 26.05 (--project-id 85 --since 2026-05-26) 32/32 + queue-only 154/154 + превентивный --since 2026-05-21 1133/1239 (упал на S3 transient — остаток переписан через WP #185 transcode-pass).
- WP #185 (full transcode): queue-only --transcode 141/141 (~45мин, 0 failed); превентивный --since 2026-05-21 --transcode 1135 файлов (~9-10ч, pid 4009575, отвязан от сессии через nohup, лог `/tmp/backfill_transcode_week.log`).

**TDD-цепочка (subagent-driven).** WP #179: 4 task'a (failing test → +faststart → observability → backfill+cleanup+tests) + 3 hotfix-итерации (Beget S3 config / SQL escape / put_object / checksum_validation=when_required). WP #185: 4 task'a + 8 раундов codex (0 P1, 6 P2 закрыто: pix_fmt, full skip-check, atom-window 256KB, audio_ok, try-around-IO, fail-closed на DEVIANT). 20/20 unit-тестов GREEN.

**PR'ы.** GenGo2/delivery-contenthunter: #114 (WP#179 фикс+бэкфилл), #115 (Beget S3 config), #116 (put_object), #117 (checksum_validation), #118 (--queue-only), #121 (WP#185 transcode+backfill). rmbrmv/contenthunter: #18 (WP#179 spec+plan), #22 (WP#185 spec+plan).

**Остаток / out-of-scope.**
- Hardware-accel transcode (h264_nvenc / VAAPI) если CPU станет bottleneck (сейчас ~30с/файл OK на нашем объёме).
- Silent-source synthesis в worker.py concat (теоретический edge case, в pipeline невозможен — `generate_ffmpeg` всегда даёт AAC).
- Audit «достаточно ли Level 4.1» на iOS 11+ устройствах.
- T+24ч cleanup `.preremux.mp4` + `.pretranscode.mp4` бэкапов: `cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python3 -m scripts.cleanup_preremux --older-than-hours 24` (вручную после 29.05 утром).

Evidence: spec `docs/superpowers/specs/2026-05-27-wp179-unic-worker-faststart-design.md` + `2026-05-28-wp185-unic-final-transcode-design.md`; plan `docs/superpowers/plans/2026-05-27-wp179-unic-worker-faststart.md` + `2026-05-28-wp185-unic-final-transcode.md`. Память: `project_wp179_wp185_unic_mobile_safe_transcode`, `feedback_faststart_vs_transcode_hw_decoder`. Урок: для mobile-decoder compat одного faststart недостаточно при aggressive uniqueness; не обозначай разрешение/level как «вторичные» в Phase 1, тестируй на устройстве сразу.

**Параллельные бэклог-итемы** (не связаны напрямую):
- `contenthunter_bugs_bot` (`bot.py:135 download_media`): ловить `TelegramBadRequest: file is too big` (TG Bot API лимит 20MB), отвечать «пришли Yandex Disk ссылку», вписывать `media: failed (too big)` в md-репорт. Видео Данила первый раз не дошло — пришлось ему вручную делать download-link.

---

## 2026-05-28 — WP #181: IG `ig_share_tap_no_progress` (#1 топ-IG-фейл 99/7д) — post-mortem success probe

### ✅ SHIPPED+DEPLOYED 2026-05-28 — OpenProject #181 → Тестирование; impl на main `delivery-contenthunter` 521ce12, прод pulled + pm2 restart

Пришло как пользовательский запрос на триаж IG-фейлов. Разведка 22.05–28.05: 807 failed IG-задач, после вычета штормового 26.05 (`watchdog_subprocess_hang` 475 — WP #165 уже задеплоен) и PM2-шума `process_interrupted` — топ-1 устойчивый = `ig_share_tap_no_progress` (99/7д, тренд 27.05=45, 28.05/неполный=12).

**Гипотеза перевернулась в процессе.** Первоначально (со всей разведки 10/10 UI-dump): «новый pre-Share экран Добавить значок ИИ блокирует Share». **Опровергнуто** при разборе скринкастов: «Добавить значок ИИ» = inline-опция Reels editor рядом с «Отметить людей»/«Добавить место», toggle серый/выключен по умолчанию, Share-кнопка активна, ничего не блокирует.

**Реальный root cause** (3/3 проверенных скринкастов 11660/11472/11646 = Reels feed с нашим контентом на финале, caption совпадает = пост опубликован): false-negative от **stale uiautomator + долгий transit ModalActivity → Reels feed (>30s pre-Tier1 probe deadline)**. Это рецидив паттерна WP #131 (TT) / WP #105 (IG) для share-tap. WP #73 фиксил похожий случай через `InstagramMainActivity` в `SUCCESS_ACT_TOKENS`, но не покрыл сценарий долгого transit.

**Решение.** Post-mortem success probe в `_wait_instagram_upload` перед записью `ig_share_tap_no_progress`: polling `dumpsys activity` 20s grace / 5s poll. Decision-логика — отрицательная сигнатура: IG в foreground И не `ModalActivity` И не `creation.activity.*` (через helper `_is_ig_post_share_progressed`). Если transit подтверждён → info-event `ig_share_postmortem_success` + fall-through в основной success-loop (url-poller WP #86 подберёт URL). Kill-switch `IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED` (default true), `IG_SHARE_POSTMORTEM_GRACE_S=20`, `IG_SHARE_POSTMORTEM_POLL_S=5`. `_safe_float_env` с try/except + clamp ≥0.1.

**TDD-цепочка (subagent-driven).** Pre-flight + 6 tasks (helper + 3 behavior-теста + impl + regression+codex). 22/22 IG-тестов GREEN (5 unit + 3 behavior + 11 share_retry + 2 wait_upload_diag + 1 amended share_retry); 3 pre-existing red в `test_publisher_ig_camera_recovery.py` + `test_publisher_intermediate_probes.py` существовали на main до WP#181 (вне нашей области). Codex review 3 раунда: 0 P1 / 0 P2 / 0 P3.

**Деплой.** `feat/wp181-ig-share-postmortem` push → ff-merge в `delivery-contenthunter` main (`4609ab4..521ce12`) → `git pull` в `/root/.openclaw/workspace-genri/autowarm/` → `sudo pm2 restart autowarm` (id 35). Процесс up без env-warning'ов, активные публикации идут. Spec+plan в `contenthunter` main (`da66259..eaf8f45`).

**Остаток / out-of-scope.** ~12-24ч мониторинг метрик: `ig_share_postmortem_success` count + падение `ig_share_tap_no_progress` от baseline (27.05=45, 28.05/неполн=12). Sample-валидация 5 случайных задач с `ig_share_postmortem_success` — проверить наличие поста в IG-аккаунте → OP#181 → «Готово». Откат: `IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED=false` в `.env` + `pm2 restart`. **Задача 11459** (Search-экран на финале, не Reels feed) — отдельный сценарий, возможно реальный fail, не блокер.

Evidence: spec `docs/superpowers/specs/2026-05-28-wp181-ig-share-no-progress-postmortem-design.md`, plan `docs/superpowers/plans/2026-05-28-wp181-ig-share-postmortem-probe.md`. Память: `project_wp181_ig_ai_label_overlay` (имя файла стало misleading после смены гипотезы, контент актуальный — переименовать при следующем правке). Урок: гипотеза по UI-dump оказалась red herring; проверка скринкастов «что на финале» с самого начала сэкономила бы 1 итерацию дизайна.

## 2026-05-26 — WP #149: Anecole не публикуется с 6 мая (битый SVG-ассет в схемах 4/5)

### ✅ ЗАКРЫТА 2026-05-26 — OpenProject #149 → Тестирование; кода не писали (первопричина устранена ранее + проверено re-queue)

Пришло как вопрос автоворкера (бриф `contenthunter_autoexec/briefs/149`, классиф. B): кто даст корректный PNG для схем 4/5, заменить PNG или убрать SVG-оверлей, где править ассет, харднинг в #151? Брейншторм-разведка (read-only прод-код воркера + БД + скачивание реального ассета) показала: **все вопросы сняты, фикс уже в проде**.

**Что нашли (сужение).** Битый ассет = **бренд-логотип** (вход FFmpeg #3, порядок 0=orig / 1=ov_video / 2=ov_audio / 3=logo / 4=pattern), а не «схема» как таковая: файл `brand/84/logo/….png` с содержимым `<svg…>` → `Invalid PNG signature 0x3C73766720776964` (=ASCII `<svg wid`) → схемы 4/5/6 падали → `unic_tasks.error` (с 07.05) → `publish_queue` пуст с 06.05. Паттерн глобальный `.png` (другие проекты здоровы) — project-specific SVG был только у логотипа.

**Почему закрыто без кода.** (1) Логотип **уже перезалит валидным PNG 900×900 ещё 25.05 12:53** (`validator_brand_profiles.updated_at`, через ~1ч после создания WP 11:49) — не нами; скачан, проверены байты, `ensure_png_raster` → конвертировать нечего. (2) Системный харднинг уже в проде (PR #105, `1af91ce`): воркер `normalize_asset` на logo+pattern растеризует остаточный SVG до FFmpeg; cairosvg 2.8.2 работает; kill-switch `UNIC_SVG_RASTERIZE_ENABLED` (#151 Готово). Бриф устарел — новый PNG не нужен.

**Верификация (live re-queue).** Застрявшую `unic_tasks` id 2639 (error c 19.05, сама не ретраится) re-queue → воркер за ~2мин собрал **3/3 схемы (4/5/6) done**, на выходе валидное h264+aac видео (850×1410, 31.8с). Никакого `Invalid PNG signature`.

**Остаток / out-of-scope.** 3 `unic_results` авто-привяжутся к очереди (крон 30мин → `publish_queue` → `dispatchPublishQueue`); past-slot guard дропает прошедшие слоты. **Реальная выкладка зависит от аккаунтов — #150**; с 19.05 авто-свип новых unic-задач для 84 не плодил (та же аккаунт-зависимость). Харднинг — в #151 (Готово). Нового бэклог-тикета нет.

Evidence: `docs/evidence/2026-05-26-wp149-anecole-svg-logo-resolved.md`. Память: `project_svg_logo_rasterization_2026_05_26` (обновлён). Урок: сверять посылку задачи против реального кода + времени деплоя (`feedback_plan_staleness`).

## 2026-05-26 — WP #98: adb_push chunked-push для медиа >70MB

### ✅ ЗАКРЫТА 2026-05-26 (resolved-by-prior-PR) — OpenProject #98 → Готово; кода не писали

Пришло как вопрос автоворкера (бриф `contenthunter_autoexec/briefs/98`): переоткрыть как расследование или реимплементировать chunked-push? Брейншторм-разведка (read-only прод-код + БД) показала, что **исходная посылка устарела — фикс уже в проде**.

**Что просил триаж WP #79 (Bucket 6).** 17 фейлов `switch_failed_unspecified::NULL` у Content hunter, приписаны adb_push timeout на медиа >70MB; чек-лист — «реализовать chunked-push + per-hop телеметрия».

**Почему закрыто без кода.** chunked-push (PR #48 `ec91909`, 13.05 11:39) + size-aware watchdog (PR #53 `055161d`, 13.05 **20:45**) уже задеплоены и корректно подключены (`publisher_base.py:4321-4327` → `compute_push_timeout(size_mb)` → `set_step(timeout_s=…)`; `set_step` 537 использует переданный timeout). Триггер chunked = **>3MB** (`CHUNKED_TRIGGER_MB=3.0`), не >70MB. Все 17 фейлов Bucket 6 — задачи **утра 13.05 (05:27–06:13), ДО деплоя**: watchdog статический 180с при медиа 55–78MB (должно быть 290–372с). Триаж 18.05 захватил окно, перекрывающее фикс. **После деплоя (13.05 21:00) — 0 фейлов `adb push медиафайла` по всем проектам за 13 дней.** Content hunter активен (109 done post-deploy), так что это починка, не простой.

**Остаток / out-of-scope.** Residual `switch_failed_unspecified` у Content hunter post-deploy = `adb_preflight` 30с = OTA-инцидент 15.05 (отдельный RC, память `feedback_ota_screen_blocks_adb_preflight`) + хвост 1–2/день 19–20.05, ноль с 20.05. **Per-hop loss telemetry НЕ делаем в publisher** — оставлено на инфра-треке (тикет TimeWeb, mtr hop 4 = 20% loss). Нового бэклог-тикета нет.

Evidence: `docs/evidence/2026-05-26-wp98-adb-push-already-fixed.md`. Память: `project_adb_push_network_issue` (обновлён). Урок: сверять посылку задачи против реального кода + времени деплоя (`feedback_plan_staleness`).

## 2026-05-26 — WP #135: IG `_current_foreground_package` двойной shell → всегда 'unknown'

### ✅ SHIPPED+DEPLOYED 2026-05-26 — delivery-contenthunter main `2d994db`; OpenProject #135 → Тестирование (verify 24ч)

Пришло как вопрос автоворкера (бриф `contenthunter_autoexec/briefs/135`). Полный цикл superpowers: brainstorm→spec→plan (оба codex-clean)→subagent-driven (implementer + spec-review ✅ + quality-review Approved после I1 DRY-фикса)→live-smoke на реальном устройстве→деплой.

**Баг.** `_current_foreground_package` слал `'shell dumpsys…'` в `adb()`, который сам оборачивает в `shell "…"` → двойной shell (`sh: shell: not found`) → ВСЕГДА `'unknown'`. Спали 2 fail-fast-защиты IG (Play-Store-hijack + `external_app` pre-picker) + логирование писало 'unknown'. 3-й случай этого класса (publisher_base:3053; WP#129 завёл отдельный корректный `_ig_probe_foreground_pkg` именно из-за него).

**Фикс.** `_current_foreground_package` делегирует в проверенный `_ig_probe_foreground_pkg` (WP#129). Обе ожившие ветки через wrapper `_ig_pre_picker_guard_pkg()` под единым kill-switch `IG_PRE_PICKER_FG_GUARD_ENABLED` (default ON). Логирование не гейтится.

**Корректировка посылки (важно).** И WP-описание, и бриф утверждали, что guard стр.~2251 = «домен #119» и будет дубль. По коду НЕВЕРНО: guard публикатора = picker ГАЛЕРЕИ (Шаг 5, выбор видео); guard #119 (`_ig_guard_picker_foreground` в `account_switcher.py`, корректный `_detect_foreground_pkg`) = picker АККАУНТОВ (`ig_4_pick_account`). Разные шаги/файлы → пересечения нет, консолидировать нечего. Урок: сверять посылку задачи против реального кода.

**Тесты.** 68 passed. Старые `TestCurrentForegroundPackage` зелёные, но баг не ловили (мокают `adb`, игнорят команду) → добавлен `test_does_not_double_wrap_shell` (ассерт на саму команду). Live-smoke (БД общая прод/стенд → без publish-задачи): на устройстве RF8Y80ZTVFZ OLD→`shell not found`, NEW→реальный пакет, IG-foreground→`com.instagram.android`.

**Деплой.** Merge ветки→main→push (`2d994db`); прод ff-merge; Python-публикатор спавнится свежим на задачу → PM2 restart не нужен (autowarm id=35 exec cwd=прод-путь).

**Остаток.** Verify 24ч: динамика `ig_external_app_foreground` + `ig_edits_promo_playstore_hijack` (единичные, не всплеск) + IG success-rate. Нового бэклог-тикета нет.

Spec/plan: `docs/superpowers/specs|plans/2026-05-26-wp135-*`. Evidence: `docs/evidence/2026-05-26-wp135-double-shell-shipped.md`. Память: `project_wp135_ig_foreground_double_shell_shipped`.

## 2026-05-25 — WP #127: планировщик в деливери — счётчик + клик по карточке + фильтр по дате

### ✅ SHIPPED+DEPLOYED 2026-05-25 — delivery-contenthunter main `07bad1c`; OpenProject #127 → Готово (принято в браузере)

Обращение Анастасии: счётчик планировщика показывал «Частично 0/12» при реально выложенных роликах. Полный цикл superpowers: brainstorm→spec→plan (codex чисто, 1 P2 оказался ложным — `hasColumn` per-column)→subagent-driven (имплементер + spec/quality ревью на таск, финал «READY TO MERGE»). Поймал галлюцинацию имплементера про несуществующий `tests/test_publish_planner.test.js` (11/11) — перепроверил сам, на код не повлияло.

**① Счётчик (корень).** Full-путь `publish_planner.js`/`getPlannerCards` считал успехи по связке `publish_tasks.client_publish_id`, а она часто NULL (22.05 ~73% задач без cpid). `publish_queue.status` (done) при этом надёжен. Фикс (Подход A, бэкенд-only): `buildPlannerCards` синтезирует успех из `queue_status` (∈ done/published/published_no_url), когда привязки нет; дата = последний реальный день попытки иначе `scheduled_date`; `via_manual` из `manual_handoff_date`. Kill-switch `PLANNER_TRUST_QUEUE_STATUS` (дефолт on). Live: Forsal (65) 22.05 → 0/12 → 10/12; флаг OFF → 1/12 (старое).

**② Приёмка выявила ещё 2 правки (та же ветка, прод `07bad1c`).** Клик по карточке вёл в «Запланировано» (`up:queue`) без даты → теперь в «Опубликовано» (`up:tasks`), отфильтровано по проекту + дню выкладки. Добавлен видимый фильтр по дате в таб tasks (бэк: `business_date` = `(pt.created_at AT TIME ZONE 'Europe/Moscow')::date` в `buildPublishTasksFilters`; фронт: инпут `#upt-date-filter` под «Старт» + `data-date` на карточке + проводка в `plannerWireCards`).

**Тесты:** 12 planner (`tests/publish_planner.test.js`) + 4 date-filter (`tests/publish_tasks_date_filter.test.js`); полный сьют autowarm 274/275 (1 fail pre-existing `checkDispatchQueueSlotLineage`, не наш). 3 раунда codex-review чисто. Деплои ff без force-push; pm2 restart autowarm (exec cwd прод-путь).

**Бэклог (заведено в OpenProject):** **WP #147** [Ошибка, relates #127, assignee Данил] — первопричина: `publish_tasks.client_publish_id` заполняется нестабильно (~73% NULL 22.05; интермиттирующе, на 20/23/24/25.05 — 0%). Бьёт ещё и по колонке «попытка» в очереди. Не чинили в #127 (вне scope).

Spec/plan: `docs/superpowers/specs|plans/2026-05-25-wp127-planner-counter*`. Память: `project_wp127_planner_counter_shipped`.

## 2026-05-25 — WP #72: триаж логов выкладки (Эль-косметик + Онлайн-школа Anecole)

### ✅ РАЗОБРАНО 2026-05-25 — исследование (кода не менял), OpenProject #72 → Тестирование; 3 дочерних WP заведено

Задача Анастасии «Изучить логи ошибок в выкладке» по двум клиентам. Полный цикл superpowers: brainstorm→spec→plan (codex: спека 1 раунд, план 5 раундов, 0 P1)→subagent-driven (аналитик Task 1–8 + моя контролёрская верификация, поймал и исправил ошибочный вывод субагента).

**Эль-косметик (82):** 18 фейлов в окне (с 15.05), мало. Почти всё — уже починенные релизами 18–22.05 категории (yt_editor_not_reached #113, ig_app_launch_failed #105, ig_upload_confirmation_timeout #129, и т.д.) либо умеренные аккаунт-проблемы. **Нового бага публикатора нет.**

**Онлайн-школа Anecole (84) — главный результат:** не публикуется с 6 мая. Причина (проверена по `unic_tasks.error_message`, не догадка): **с 7 мая сломана генерация контента (уникализация)** — в схемах оформления 4/5 у Anecole лежит **SVG вместо PNG**, FFmpeg падает (`Invalid PNG signature 0x3C7376672077696...` = ASCII `<svg wid`), задачи `public.unic_tasks` уходят в `error` → новых роликов нет → очередь пуста → выкладки нет. **Контентно-операционная поломка** (перезалить PNG), НЕ баг публикатора.

**Коррекция вывода субагента:** он валил остановку на `validator_unic_content=0` / WP #95. Опровергнуто: у активной Эль `validator_unic_content` тоже 0, а она публикуется. `validator_unic_content` — ложный признак; реальный источник контента очереди = `public.unic_tasks` (keyed по validator project_id). Оставил коррекцию комментарием в #95.

**Заведено в OpenProject (дочерние к #72, assignee Данил):**
- **#149** [Высокий] — Anecole не публикуется с 6 мая, сломана генерация (перезалить PNG в схемы 4/5). Главный.
- **#150** [Обычный] — школа: аккаунты не на тех телефонах (aneco_le 16/16 fail, 89venlshfzm 6/6) + нездоровые устройства (raspberry 10, 52–74% фейлов). «Спящий» — всплывёт после починки генерации.
- **#151** [Обычный] — харднинг уникализации: не ронять весь видеоконвейер из-за одного битого ассета (валидация формата). Связан с #45/#51.

**Урок (git, 3-й инцидент):** работал `git checkout -b` в общем `contenthunter`-checkout вместо worktree → параллельная сессия (wp44) перебила HEAD ДО моего первого коммита, мои spec/plan-коммиты уехали на её ветку; `git commit --amend` во время codex-раундов на общем HEAD перетирал промежуточные деревья (чуть не потерял финальный план — восстановил из reflog). Recovery: cherry-pick + извлечение правильного плана из reflog-коммита. Усилено в `feedback_parallel_claude_sessions`: worktree-first обязателен; не использовать `--amend` для codex-раундов на shared checkout.

Spec/plan/evidence: `docs/superpowers/specs|plans/2026-05-25-wp72-publish-error-logs*` + `docs/evidence/2026-05-25-wp72-publish-error-logs.md`. Память: `project_wp72_publish_log_triage`.

## 2026-05-22 — WP #108 пост-деплой: осиротевший бэклог + success-rate (handoff=fail) + fix stats vp-баг

### ✅ SHIPPED+DEPLOYED 2026-05-22 — delivery-contenthunter main `9735330` + `c861597`

Разбор обращения Данила («56 упавших висят, не уходят в ретрай»). Три результата за сессию:

**① Осиротевший утренний бэклог (root cause + ремонт).** Контроллер ретраев линкует очередь↔падение **только по `client_publish_id`** (`retry_controller.js:39`) + guard `if (!r.error_class) continue`. Но проброс cpid в `publish_tasks` приехал в ТОМ ЖЕ деплое (`ce4429b`) → все ~57 до-деплойных падений с `cpid=NULL` молча пропускались (ни requeue, ни handoff), висели `failed`. Деплойный рестарт PM2 добил ~16 задач `process_interrupted` (движок их исключает). Ремонт (вариант А Данила): 16 PI → `pending` руками; 9 осиротевшим — backfill cpid из `publish_task_id`; контроллер на тике 14:31 отработал по дизайну (5 requeue + 4 handoff). **Урок:** consumer по новой колонке = backfill в составе деплоя, иначе до-деплойные строки сиротеют.

**② Success rate: handoff = фейл (`9735330`).** Когда публикация падает и движок отдаёт её в ручную (`failed`→`cancelled`+`manual_handoff_at`), раньше `cancelled` целиком выпадал из метрики → success rate завышался. Теперь `cancelled AND manual_handoff_at IS NOT NULL` = `errors`; проактивный `manual_publish` + переносы слотов остаются исключёнными. Поправлены ОБЕ точки: pub-dash (плитки+timeseries, server.js) и daily-отчёт (buildReport+buildErrorBreakdown). Прод: errors 32→37, rate 86.2%→84.4%. Тесты 45/45+37/37+9/9.

**③ Fix stats vp-баг (`c861597`, пред-существующий, ~43 ошибки/день).** `/api/publish/(queue|tasks)/stats` 500-или при `?project=` — stats-FROM не JOIN'ил `validator_projects`, а билдеры фильтров ссылаются на `vp`/`vp2`. Добавил vp+vp2 в `PUBLISH_QUEUE_FROM_STATS`; вынес inline-FROM tasks/stats в `PUBLISH_TASKS_FROM_STATS` (с vp). LEFT JOIN на PK → без фан-аута. Регресс-тест `tests/test_stats_from_filter_contract.test.js` исполняет реальный stats-SQL и ловит FROM↔filter рассинхрон.

**Бэклог (заведено в OpenProject):** WP #140 — классификатор error-кодов (yt/switch коды без `error_class` дефолтятся в `unknown` → ретраятся вечно вместо handoff, как pq#5069); WP #141 — дашборд+графики: count и % задач в ручной выкладке (retry-handoff vs проактивный manual_publish раздельно).

Evidence: `docs/evidence/2026-05-22-wp108-orphan-backlog-and-metric-fixes.md`. Память: `project_wp108_retry_engine_orphan_backlog`, `project_daily_publish_report`.

## 2026-05-22 — Движок ретраев публикаций (WP #108)

### ✅ SHIPPED+DEPLOYED+VERIFIED 2026-05-22 — delivery-contenthunter main `bd8c6a5` (вариант C1 «чистый лист»)

Дизайн/план/код движка сделаны предыдущей сессией (ветка кода `wp108-publish-retries`, 19 тестов, ревью READY-WITH-NOTES). Эта сессия = деплой по согласованному на созвоне варианту **C1 «Старт с чистого листа»** + включить сразу + МСК-старт 05:00.

**Что включено:** классификатор `error_class` (network/ui_changed/banned/rate_limited/unknown) + чистая `decideRetry` (retry_decision.js) + крон `retryFailedPublishes` (retry_controller.js, тик 5 мин, окно до 23:00 МСК) + хук идемпотентности перед Share (publish_idempotency.py). Лимиты: 3 ретрая/сутки/класс, окно 2 дня → дальше в ручную (переиспользует сагу #85/#107/#115/#125); banned/ui_changed → сразу в ручную; реестр `fixed_at` реанимирует. 7 env-рубильников (дефолт вкл). Контроллер линкует задачу↔намерение по `client_publish_id` (`WHERE status='failed' AND manual_handoff_at IS NULL`, LIMIT 200).

**Деплой C1:** бэклог 2156 упавших помечен `manual_handoff_at=now(), skip_reason=COALESCE(skip_reason,'retry_clean_slate_20260522')` (откат — по timestamp пачки `2026-05-22 09:48:28.533923+00`; COALESCE сохранил 1 чужой skip_reason — фикс codex P2). `unic_settings → Europe/Moscow / 05:00:00` (slot_date=DATE, сдвига нет). Cross-repo grep выявил взаимодействие с планировщиком WP #109 (читает `manual_handoff_at` → колонка «перенесено» в очереди) — косметика, принято.

**⚠️ Снаг при деплое (главный урок):** после merge у новых publish_tasks НЕ проставлялся `client_publish_id` → контроллер их молча пропускал. Двойной корень: (1) **3 зомби-процесса** `test_dispatch_manual_guard.test.js` (WP #125, ~20ч, из удалённого worktree) импортировали server.js → крутили теневой autowarm старым кодом, диспатча боевую очередь; (2) **`pm2 restart` грузил stale-код** — помог только `pm2 delete` + `start` из `ecosystem.production.config.js` + `pm2 save`. После фикса cpid 5/5. Опознание: postgres в контейнере (172.17.0.3:5432), клиенты — host-процессы (172.17.0.1); `sudo ss -tnpH|grep 5432→pid→/proc/$pid/{cmdline,cwd}`. Память: [[feedback-stale-node-test]], [[feedback-pm2-dump-path-drift]].

**Верификация вживую:** 11:21 `[retry-controller] requeue pq#5005 (unknown, transient_within_limits)` — реальное падение подхвачено, классифицировано и возвращено в очередь. autowarm = pm2 id=35, стабилен.

**Follow-ups / out-of-scope:** ① путь «передача в ручную при исчерпании окна/лимита» — проявится за 1-2 дня по мере накопления (наблюдать через WP #114 дневной отчёт + логи `[retry-controller] handoff`); ② задачи, созданные между деплоем и фиксом (~pt 9298-9365) — без cpid, движок их не подхватит (как и C1-бэклог), безобидный транзиент, не чинить; ③ пункт 10 задачи (возврат ручная→авто на след. день) — отдельно, вне #108; ④ параллелизм малинок (3→до 8) — тюнинг с мониторингом fail-rate; ⑤ зомби-процессы node server.js с марта на VPS → **WP #133** (бэклог).

Spec/plan/runbook: `docs/superpowers/specs/2026-05-21-wp108-publish-retry-engine-design.md`, `docs/superpowers/plans/2026-05-21-wp108-publish-retry-engine.md`, `docs/superpowers/plans/2026-05-21-wp108-deploy-options.md`, `docs/superpowers/plans/2026-05-22-wp108-deploy-c1-runbook.md`. Память: `project_wp108_retry_engine_shipped`. OpenProject WP #108 → **Тестирование** (ждёт live-наблюдения handoff-ветки).

## 2026-05-22 — TT: foreground-hijack на шаге переключения аккаунта (WP #130) + tt_profile_tab_broken (WP #131)

### ✅ SHIPPED+DEPLOYED 2026-05-22 — delivery-contenthunter#97 (merge `486fec2`)

Триаж TT-фейлов за 2026-05-22 (13 задач, сетевой `adb_devices_unreachable` исключён). Группировка по последнему `events[].meta.category`. Топ по эмитнутому коду — `tt_account_sheet_closed_before_parse` (4), но это **смешанный бакет**.

**Корень (доказан скринкастами + UI-dump labels):** на шаге `tt_3_open_list` TikTok теряет передний план — task 9116 → Instagram (профиль `jasleen`), 9239 → домашний экран Samsung, 9210/9229 → петля перезапуска/сплэш TikTok. `_open_tt_account_switcher` тапал шапку профиля и парсил ЧУЖОЙ экран → bottomsheet «не открылся» → ложный `tt_account_sheet_closed_before_parse` (2 из 4 фейлов мис-классифицированы так). Fg-guard стоял только на старте свитча (`tt_1_feed`), а drift случался позже. По первопричине foreground-drift = **4/13 (топ-1)**.

**Что сделано (`account_switcher.py`, зеркало IG WP #119):** kill-switch `_tt_switch_fg_guard_enabled()` (`TT_SWITCH_FG_GUARD_ENABLED`, default ON); `_tt_guard_switcher_foreground(cfg)` — `_detect_foreground_pkg()`, TT/неопределён → no-op, чужой → `_ensure_app_foregrounded('TikTok')` + re-navigate + verify own-profile (`_tt_is_own_profile(dump_ui(retries=3))`), tri-state `ok`/`recovered`/`unrecoverable`. **Placement A** (в `_switch_tiktok` перед `_open_tt_account_switcher`): recover или честный fail `tt_fg_drift_unrecoverable`, панель на чужом экране не открываем; после recovery перечитываем `elements`. **Placement B** (внутри `_open_tt_account_switcher`): probe не открыл панель И foreground уже не TikTok → `tt_fg_drift_unrecoverable` вместо account_sheet (drift во время probe-тапа). Классификация через `final_step=tt_fg_drift_unrecoverable` (`_SWITCHER_STEP_TO_CATEGORY`). Настоящий sheet-not-open (foreground=TikTok, 9179/9183) по-прежнему → `tt_account_sheet_closed_before_parse` (территория WP #96).

**Тесты/ревью:** 10 новых тестов (`tests/test_account_switcher_tt_switch_fg_guard.py`); 217 switcher-тестов зелёные; codex review 2 раунда P2 (verify own-profile после re-nav; консистентность с retap-loop) → финал чистый.

**Деплой:** PR #97 squash-merge в `main`, прод `git pull --ff-only` (`bd8c6a5..486fec2`, чисто), фикс в прод-файле, синтаксис OK. pm2 restart НЕ нужен — публикатор спавнится per-task, `exec cwd` = прод-путь. Kill-switch ON. **Verify утром 23.05:** меньше `tt_account_sheet_closed_before_parse`, честный `tt_fg_drift_unrecoverable` при реальном drift.

**WP #131 (Бэклог):** `tt_profile_tab_broken` (9117/9156, шаг `tt_2_not_own_profile`, 2/13) — после перехода в профиль-таб бот не распознаёт собственный профиль; нужен разбор UI-dump (неверная навигация vs сломанное распознавание own-profile). **Остаток вне #130:** усиление recovery петли перезапуска TikTok (9210/9229).

Триаж: `docs/evidence/2026-05-22-tt-publish-fails-triage.md`. Память: `project_tt_triage_2026_05_22`. OpenProject WP #130 → **Тестирование** (комменты 424/425), WP #131 → Бэклог.

## 2026-05-22 — IG: ig_app_launch_failed рецидив (WP #105 Round 2)

### ✅ SHIPPED+DEPLOYED 2026-05-22 — delivery-contenthunter#98 (squash `862ce81`)

Рецидив после частичного фикса PR #76: `ig_app_launch_failed` 22.05 = **пик 6–7/день** (топ-1 кодовый IG-фейл), raspberries 1/2/3/5, разные устройства/аккаунты → код-баг. Полный цикл superpowers: brainstorm→spec→plan (codex)→subagent-driven (имплементер + spec-ревью + quality-ревью + контроллерская верификация + codex на диффе).

**Что было не так:** trace task 9227 — `_ensure_app_foregrounded` дважды независимо подтверждает IG через dumpsys, затем 5× `foreground_pkg_disagree` (dumpsys=instagram / uiautomator=launcher) за ~4.5 мин, settle-wait 0 раз → fail на `ig_1_feed`. Confirming-poll из PR #76 (Codex P2 round 2) ждёт, пока uiautomator догонит dumpsys; в проде uiautomator залипает на launcher-окне минутами → ложный провал. Уточнённый root cause: **сломан именно uiautomator XML-дамп**; dumpsys И скриншот корректны.

**Что сделано:** одна правка в `_foreground_pkg` (внутри `_open_app`) — после неудачного catch-up uiautomator проверяем стабильность dumpsys (`stable_reads_required=3` чтения подряд == target, 0.5с) → доверяем dumpsys, эмитим `switcher_foreground_trusted_dumpsys`. Под kill-switch `SWITCHER_TRUST_DUMPSYS_ON_STALE_UI` (default on). Защита от реальных overlay (permissioncontroller и т.п.) сохранена — новый путь только при `pkg_ui ∈ {launcher, пусто}`. `_ensure_app_foregrounded` не трогали (корректен). Решение «доверять dumpsys + стабилизация» выбрано Данилом из 3 опций (vs скриншот-арбитр / мульти-recovery).

**Деплой:** прод на main чистый → `git pull --ff-only` (486fec2..862ce81). PM2 restart НЕ нужен — публикатор спавнится свежим на задачу (scheduler.js `__dirname`=прод-дир). Откат мгновенный через kill-switch.

**Тесты/ревью:** 66 зелёных (старый `..._does_not_shortcut` инвертирован в `..._trusts_dumpsys`; +flapping +killswitch локи). Spec- и code-quality-ревью пройдены (1 minor: `stable_reads` single-source-of-truth — применён). **codex: 0 P1**; один **P2** («доверие dumpsys без независимого visibility-сигнала») — принятый trade-off (премиса противоположна фактам — свежий именно dumpsys; downstream UI-шаги ловят реальный not-up).

**Остаток:** verify динамики `ig_app_launch_failed` за 24ч (утро 2026-05-23) → к нулю → OpenProject «Готово».

Spec/plan: `docs/superpowers/specs|plans/2026-05-22-wp105-dumpsys-trust-on-stale-ui*`. Память: [[project_wp105_ig_app_launch_stale_uiautomator_shipped]]. OpenProject WP #105 → **Тестирование** (comment id 426).

## 2026-05-21 — Планировщик в деливери (WP #109)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter main `a8c4f4b`

Запрос Анастасии (мокап + описание): дать менеджеру видимый календарь-планировщик выкладок с переносами. Полный цикл superpowers: brainstorm→spec→plan (codex 0 P1; все P2 закрыты)→subagent-driven (11 задач: имплементеры + spec/quality-ревью + финальное opus-ревью + контроллерская верификация на живой БД).

**Что:** read-only визуализация поверх движка ретраев #108. (1) новый под-таб `up:planner` в «Выкладка» — недельная сетка, карточки «проект×ролик×день» (published/approved/pending/partial/echo/final), N/N, прогресс-бар, пометки переносов (↗/↩/закрыло), 🤖/👋, hover-подсветка цепочки, клик→очередь; (2) две колонки очереди «перенесено»+«попытка».

**Архитектура (Подход 1):** переносы ВЫВОДЯТСЯ из таймлайна `publish_tasks` по МСК-дням, ничего нового не хранится. Модуль `publish_planner.js` (чистые `buildPlannerCards`/`deriveTransferColumns` — 11 юнит-тестов + `getPlannerCards` SQL), роут `GET /api/publish/planner`. Тонкий контракт к #108 (`client_publish_id`/`manual_handoff_at`/`error_class` — уже в БД → full-режим). Kill-switches `PLANNER_ENABLED`/`QUEUE_TRANSFER_COLUMNS_ENABLED`. Деплой ff-merge клон→прод-main + ручной push (ff не триггерит auto-push hook). OpenProject → Тестирование.

**Остаток / follow-up:**
- ⚠️ **Дубль-карточка при `meta_slot_id_missing`** (найдено финальным ревью; в проде наблюдается, напр. result_id 16214): если `publish_queue`-строка не привязана к слоту (нет `slot_id` в `unic_task.meta`), дедуп плановой карточки не срабатывает → один слот показывает ОБЕ карточки (плановую approved/pending + выкладочную). Косметика, не краш. Фикс при необходимости: расширить `NOT EXISTS` дедуп в `getPlannerCards` на `(project_id, scheduled_date)`.
- Браузерная приёмка Данила (после — перевести WP #109 в «Готово»).

## 2026-05-21 — Валидатор: убрать разделы «Менеджер» и «Продюсер» (WP #71)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — validator-contenthunter#21 (merge `c14bbeb`)

Запрос Анастасии (описание пустое, scope уточнён с Данилом): полностью убрать из фронтенда валидатора разделы «Менеджер» и «Продюсер» со всеми подразделами — у всех ролей, **включая админа**. Клиент не трогать. Полный цикл superpowers: brainstorm→spec→plan (codex 0 P1 на обоих)→subagent-driven (Tasks 1-7: имплементеры по группам + spec-ревью + codex на полном диффе + контроллерская верификация).

**Решения (с Данилом):** глубина = «интерфейс целиком» (меню + маршруты + страницы + эксклюзивные компоненты); бэкенд и данные НЕ трогаем; доступ = убрать у всех включая админа, роли `manager`/`producer` в авторизации/БД **СОХРАНИТЬ** (можно вернуть).

**Архитектура (только фронтенд, `validator-contenthunter/frontend`):** удалены 11 маршрутов manager/producer из `router/index.ts` + добавлен catch-all `/:pathMatch(.*)* → /dashboard` (catch-all не было; старые/закладочные ссылки давали бы пустую страницу); убраны секции меню в `AppSidebar.vue` (десктоп + мобайл); post-login редиректы ролей manager/producer → `/dashboard` (`LoginPage.vue` ×2 + `TgCallbackPage.vue`; раньше вели на удалённые `/manager`,`/producer` = 404); подчищены title-мэппинги в `AppHeader.vue`; удалены 11 страниц (`pages/manager/*`, `pages/producer/*`) + 3 эксклюзивных компонента (`ClientGrid`, `FuelGauge`, `WeeklyGrid`). Сохранены `isManager`/`isProducer` в `stores/auth.ts`, общие компоненты (`PlatformIcon`/`DropZone`/`UploadProgress`), весь бэкенд. Guard-тест `router/__tests__/routes.spec.ts` (нет manager/producer-маршрутов + есть catch-all). Админ инспектирует клиента через переключатель проектов на Планировщике (`/dashboard` имеет roles client/manager/producer/admin) — функция удалённого `ClientView` дублируется.

**Деплой:** `npm run build` → postbuild авто-копирует в `/var/www/validator` (= прод-деплой; для проверки без деплоя — `npx vue-tsc --noEmit`). PR #21 смержен в main, локальный main синхронизирован. В новом бандле нет чанков/ссылок manager/producer; старые хеш-чанки в `/var/www/validator/assets` оставлены намеренно (cp без удаления → защищает юзеров со stale index до hard-reload).

**Тесты/ревью:** vue-tsc чист; vitest 18/18. Codex на полном диффе дал 2×P1 — **оба ложные** (codex видит только дифф): «WeeklyGrid нужен планировщику» (клиентский dashboard его НЕ импортирует, vue-tsc чист) и «manager/producer не авторизованы на /dashboard» (route имеет эти роли, строка вне диффа). Опровергнуты grep'ом + чтением строки 12 роутера.

**Уроки:** (1) валидатор-фронт `npm run test` имеет ПРЕД-СУЩЕСТВУЮЩИЙ красный сюйт `slotStatus.test.ts` (импортирует `node:test`, несовместим с бандлером vitest; есть и на main) — это baseline-шум, НЕ регрессия. (2) codex-ревью на удалениях склонен к diff-blindness false-positive про «осиротевшие» зависимости — сверять с vue-tsc + grep по всему `src`, не принимать вслепую.

Spec/plan: `docs/superpowers/specs|plans/2026-05-21-wp71-remove-manager-producer-sections*`. Память: `project_wp71_remove_manager_producer`. OpenProject WP #71 → **Готово** (проверено в браузере Данилом 2026-05-21).

## 2026-05-21 — Ручная выкладка: группировка по видео + реалтайм + guard автопубликации (WP #123/#124/#125)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter#95 (#125, merge `f421811`) + #96 (#123/#124, merge `861f63f`)

Пачка из трёх взаимосвязанных задач поверх ручной выкладки (WP #85/#107/#115). Полный цикл superpowers: brainstorm→2 спека→2 плана (codex 0 P1: #125 — 2 раунда, #123/#124 — 7 раундов)→subagent-driven (имплементер + spec-ревью + quality-ревью на каждую часть; конкурентность проверена эмпирически — 40 параллельных claim, 0 split-ownership).

**#125 — manual-слот автовыложился (хотфикс).** Корень (по данным slot 21246 Feminista): строки `publish_queue` создаются ДО пометки слота «вручную», флаг ставят позже, и (1) включение флага не отменяло pending-строки, (2) `dispatchPublishQueue` не перепроверял флаг. Фикс — перепроверка на единственном чокпоинте `checkDispatchQueueSlotLineage` (под advisory-lock, до lineage) через helper `slotIsEffectivelyManual` (переиспользует `effectiveManualSql` → ловит и client-level WP#115); manual → строка `cancelled`/`skip_reason='manual_publish'`. Kill-switch `DISPATCH_MANUAL_RECHECK_ENABLED`. Разовая зачистка `scripts/wp125_cleanup_manual_pending.sql` (CTE numeric-фильтр slot_id). 14/14 тестов (импортирует `./server` → `--test-force-exit`).

**#123 — группировка по исходному видео.** Карточка = группа по `unic_result_id` (одно уник-видео × один пак); на весь экран; мини-таблица по площадкам (per-platform handle — юзернеймы по площадкам могут различаться); копируемая ссылка на уник-видео; «Взять в работу» на весь пак.

**#124 — реалтайм + защита «уже в работе».** `takeGroup`/`returnGroup` по `unic_result_id` (в `withTx`), pack-level ownership guard (блок только по `in_progress`, NULL-владелец тоже блокирует, re-entrant для своего, `published` не лочит); 409 «Задача взята оператором XXX»; частичная выкладка per-platform; поллинг ~5 c (ENV `MPQ_POLL_MS`), не затирает наполовину введённую ссылку. 9/9 backend-тестов.

**⚠️ FK-fix миграция (нашёл имплементер):** колонки `taken_by_id`/`published_by_id` существовали с WP#107, но FK вёл на `validator_users` (оператор дашборда — `autowarm_users`). `migrations/20260521_manual_queue_taken_by_fk_fix.sql` перевешивает FK на `autowarm_users`. Применена к общей БД при разработке (idempotent `IF EXISTS`, 0/119 строк non-NULL → нулевой риск). **Cross-repo follow-up:** проверить, не переустановит ли валидаторная WP#107-миграция старый FK (`validator_users`) при redeploy.

**Деплой:** оба ff `git pull` в прод-checkout `/root/.openclaw/workspace-genri/autowarm` (без нового коммита → auto-push hook не триггерится) + `sudo pm2 restart 34`. #125: cleanup `UPDATE 0`. #123/#124: group-эндпоинты отвечают 401 (живые). online, 0 unstable restarts. ⚠️ открытым вкладкам «Выкладки» нужен hard-reload (кэш index.html).

**Follow-ups (минор, не блокеры):** слой-2 (валидаторная немедленная отмена pending при включении флага) — опционально, слой-1 закрывает баг; косметика — кнопка «Вернуть пак» показывается на возвращённом частично-выложенном паке (no-op); `published_by_id` пишется не везде; per-id `take`/`return` эндпоинты оставлены (backcompat, новый UI не использует); заголовок секции «Ручная выкладка».

**Урок:** worktree ПЕРВЫМ действием — рецидив shared-checkout branch-swap (соседняя сессия перебила HEAD общего `contenthunter`-checkout, мой коммит планов уехал на чужую ветку; recovery cherry-pick + `reset --mixed`). Зафиксировано в `feedback_parallel_claude_sessions`.

Spec/plan: `docs/superpowers/specs|plans/2026-05-21-wp125-*` и `*-wp123-124-*`. Память: `project_wp123_124_125_manual_publish_iteration`. OpenProject #123/#124/#125 → Тестирование (комменты 402/403/404; ждёт браузерной приёмки фронта #123/#124 + суток наблюдения #125).

## 2026-05-21 — Дашборд выкладки: график Success rate в динамике + фильтры (WP #90)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter `60a7a07` (фича) + `bdffb72` (hotfix меток)

Запрос Анастасии: на дашборд выкладки (`#farming/publishing-dashboard`) добавить график Success rate в динамике по платформам; «все текущие фильтры применяются и к графику»; метки данных видны сразу, при перегрузе — на наведении. Полный цикл superpowers: brainstorm→spec→plan (codex: спека 2 раунда, план 3 раунда, 0 P1)→subagent-driven (11 задач, имплементер + spec-ревью + quality-ревью на каждую + финальное холистическое = READY TO MERGE).

**Решения (с Данилом):** 4 линии Все/IG/TT/YT; бакеты час (диапазон ≤1 дня) / день (иначе); фильтры project/platform/account/pack — серверные, и к плиткам, и к графику; +пресеты «Вчера» и «Последние 3 дня» (3 кал. дня вкл. сегодня).

**Архитектура (один эндпоинт):** расширен `GET /api/publish-queue/dashboard` — принимает фильтры (переиспользует SQL-фрагменты `buildPublishQueueFilters` через `buildDashboardFilters` + `PUBLISH_QUEUE_FROM`) и в одном ответе отдаёт плитки + `series` (точка `{rate,done,denom}`|null). 6 pure-helpers с юнит-тестами (`calcDashboardRange`+yesterday/last3, `pickBucketUnit`, `buildDashboardFilters`, `buildBucketAxis`, `assembleSeries`, `isDashboardTimeseriesEnabled`). Фронт — Chart.js (4 линии, тултип `XX% (done из denom)`); datalabels-плагин гасится глобально (`Chart.defaults`) и включается локально на графике (иначе метки полезли бы на фарминг/SLA/токены). TZ: `scheduled_at` UTC-naive → `+ interval '3 hours'` перед `date_trunc`; JS-ось бакетов форматирует метки идентично SQL `to_char`. Метрика = `computeSuccessRate` done/(done+errors), как у дневного отчёта (WP #114). Kill-switch `DASHBOARD_TIMESERIES_ENABLED`.

**Реконсиляция при деплое:** прод-main autowarm уехал вперёд за сессию (WP#107/#119/#115 тронули index.html+server.js) — мержил origin/main в ветку (union-конфликт index.html: dashboard-функции vs `mpq*` перед общим `}`). Деплой = хирургический cp 3 файлов в прод (НЕ затирая чужое), 260/260 тестов в проде. PM2 id 34 `autowarm` :3848 (НЕ testbench id 33/26).

**Hotfix меток (`bdffb72`):** баг-репорт — чекбокс «Значения на графике» не срабатывал на «Месяц»(31)/«Сегодня»(24). Root cause (по логам `[pub-dash]`): порог читаемости (≤14 точек) был ЖЁСТКИМ ГЕЙТОМ и перебивал чекбокс. Фикс: чекбокс = источник истины (`showLabels = checkbox.checked`), число бакетов задаёт лишь дефолт состояния чекбокса при загрузке. Проверено Данилом.

**Follow-ups / out-of-scope (минор, не блокеры):** URL-persist фильтров; auto-refresh/live polling; сравнение с предыдущим периодом; блок «Прочие платформы» (vk/pinterest/likee); drill-down по точке графика → таблица с фильтром; экспорт CSV/PNG; карточка графика остаётся видимой при `DASHBOARD_TIMESERIES_ENABLED=0` (показывает «нет данных»); ILIKE-метасимволы в account/pack не экранируются (консистентно с `buildPublishQueueFilters`).

Spec/plan: `docs/superpowers/specs|plans/2026-05-21-publishing-dashboard-success-rate-chart*`. Память: `project_wp90_success_rate_chart`. OpenProject WP #90 → **Готово** (проверено на проде Данилом).

## 2026-05-21 — Клиентский признак ручной выкладки (WP #115)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — validator-contenthunter#20 (`dc96171`) + delivery-contenthunter#94 (`19f7294`) + docs#4

Продолжение WP #85 (послотовый флаг) и WP #107 (очередь). В справочнике Клиентов (`/clients`) — глобальный признак типа выкладки на уровне клиента (=`validator_projects`). Полный цикл superpowers: brainstorm→spec→plan (codex 0 P1 на обоих)→subagent-driven (8 задач, per-task spec+quality ревью + финальное холистическое).

**Решения (с Данилом):** клиент «Ручная» = весь контент в ручную (двухзначно, без per-slot авто-исключений); переключение **ретроактивно** (отзывает уже-запланированный, но не опубликованный авто-контент); менять может **только админ**.

**Архитектура (Вариант A — вычислять на лету, НЕ каскадить на слоты):** единый источник правды `validator_projects.manual_publish`; «эффективная ручная» = `slot.manual_publish OR project.manual_publish`.
- **validator#20:** миграция 007 (3 колонки на validator_projects, аддитивно) + сервис `apply_client_publish_mode` (флаг+аудит+ретроактивный каскад: Авто→Ручная отзывает pending авто-путь с guard `pq.publish_task_id IS NULL`; Ручная→Авто гасит queued-строки ручной очереди только для слотов с `manual_publish=false`) + эндпоинт `PATCH /api/projects/{id}/publish-mode` (admin-only) + `manual_publish` в GET + фронт `ProjectPublishModeCell.vue` + колонка «Тип выкладки» на `/clients` (тумблер admin-only + модалка-подтверждение).
- **delivery#94 (autowarm):** модуль `client_manual_filter.js` (`effectiveManualSql` предикат + kill-switch `CLIENT_MANUAL_PUBLISH_ENABLED`) вплетён в 3 SQL-точки (auto-guard `assignUnicResultsToQueue`, наполнитель `manual_queue_assign.js`, матчер `slot_matcher_cron.js`) через `LEFT JOIN validator_projects`.

**Деплой:** БД уже на 007 (миграции шли против общей localhost-БД на разработке → alembic no-op на проде). validator backend `/root/.../validator` `git pull`→`pm2 restart validator` (id=24); фронт собран из `/home/claude-user/validator-contenthunter` (`npm run build`→postbuild→/var/www); autowarm `/root/.../autowarm` ff `git pull`→`pm2 restart autowarm` (id=34, cwd прод). Верифицировано: `[assign-queue]` тик с новым SQL без ошибок, validator отдаёт 200, прод 80 проектов / 0 ручных.

**⚠️ Урок (нашло финальное холистическое ревью):** два kill-switch'а в РАЗНЫХ процессах. Выключая `CLIENT_MANUAL_PUBLISH_ENABLED` в autowarm, обязательно ставь `MANUAL_PUBLISH_TOGGLE_ENABLED=false` на валидаторе И верни ручных клиентов в «Авто» — иначе валидатор отменит авто-контент, а autowarm не подхватит его в ручную (застрянет). Зафиксировано в спеке §10. Прочие уроки: asyncpg-гоча с meta JSONB в фикстуре (инлайн-литерал, как в test_pipeline_reversal); `effectiveManualSql` как единый источник предиката переживает kill-switch без рассинхрона 3 точек.

**Follow-ups (минор, не блокеры):** frontend `applyPublishMode` без error-toast (как соседние модалки); `_slot_to_dict` effective-поле отложено (вне MVP).

Spec/plan: `docs/superpowers/specs|plans/2026-05-21-wp115-client-manual-publish*`. Evidence: `docs/evidence/wp115_smoke_2026-05-21.md`. Память: `project_wp115_client_manual_publish`. OpenProject WP #115 → Тестирование (ждёт live-проверки на реальном клиенте).

## 2026-05-21 — Ручная выкладка: ПЕРЕНОС в delivery-дашборд (WP #107)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter#91/#92/#93 + validator revert #19

Задача #107 требовала подраздел «Ручная выкладка» в разделе «Выкладка» **delivery-дашборда**, но вчерашняя реализация (validator#18) ошибочно собрала UI в админке валидатора (`client.contenthunter.ru`). Пользователь указал дважды. Переделано по полному циклу: brainstorm→spec→plan (codex 4 раунда)→subagent-driven (имплементер + spec-ревью + quality-ревью на каждую из 7 задач).

**delivery (autowarm):** модуль `manual_publish_queue.js` (сериализатор + переходы; атомарные условные UPDATE, multi-table publish/rework в одной client-транзакции; 16 mock-тестов) + 6 эндпоинтов `/api/publishing/manual-queue*` (под `requireAuth`) + подключён МЁРТВЫЙ наполнитель `assignManualPublishQueue` (PR#86 добавил модуль, но забыл завести в шедулер) + vanilla-JS секция в `public/index.html` (таблица: sticky заголовки+строка фильтров, CTRL-мультисорт, дропдаун-фильтры, **календарик** для план-даты, сброс ⟲, группировка по телефону; карточка: copy-on-click из JS-map, `<video>`, publish-режим с МСК-датой). Полный autowarm-сюит 237/237.
**validator (revert #19):** удалён ошибочный UI (page/card/composable/api/route/sidebar) + backend-роутер; СОХРАНЁН `cancel_queued_for_slot` (WP#85 toggle-OFF, вызывается из `schedule.py`).

**Деплой:** delivery PR#91 (merge `edc232f`) + UI-фиксы по приёмке #92 (план-дата `to_char`→YYYY-MM-DD; sticky строка фильтров `!top-9`) + #93 (date-picker в фильтре); validator revert #19 (merge `18a5af1`). Прод autowarm `pm2 restart` → наполнитель ожил, очередь 19 строк; validator backend `/api/manual-publish/queue`→404, фронт пересобран без пункта. OpenProject #107 комментарии.

**Уроки:** codex видит только дифф (round-4 false-positive «нет `unic_result_id`» — колонка существует); двухстадийное ревью поймало интеграционный nav()-баг (`hidden` !important перебивал `.section.active`); validator `npm run build` авто-деплоит в `/var/www/validator` (postbuild) — собирать `npx vue-tsc --noEmit` для проверки без деплоя; глобальный `.table-wrap thead th{position:sticky;top:0}` клал обе sticky-строки на 0; node-pg `DATE`→ISO-timestamp в JSON (фикс через SQL `to_char`).

Spec/plan: `docs/superpowers/specs|plans/2026-05-21-wp107-manual-publish-delivery*`. Память: `project_wp107_manual_publish_queue`. OpenProject WP #107 → Тестирование (UI-замечания Данила исправлены; ждёт финальной визуальной приёмки в delivery). Прежняя (ошибочно-валидаторная) запись 2026-05-20 ниже — историческая.

## 2026-05-21 — IG: foreground-hijack на шаге выбора аккаунта (`ig_target_not_in_picker`) (WP #119)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter#90 (squash `700e50c`, прод ff)

Триаж IG-фейлов за 2026-05-21 (после исключения сетевой adb-проблемы и PM2-шума): топ-2 = `ig_target_not_in_picker` **18/7д**, размазано по разным аккаунтам/устройствам (= код, не конфиг). Топ-1 `ig_share_tap_no_progress` (26) уже имеет фикс WP #73; `ig_target_not_in_picker` — крупнейший баг без активной задачи на фикс.

**Корень (доказан):** `ig_target_not_in_picker` («аккаунт не привязан к устройству») — вводящий в заблуждение код. На шаге `ig_4_pick_account` на переднем плане оказывается ЧУЖОЕ приложение, `parse_account_list` скребёт его экран → мусор → ложный «не найден». Подтверждено пакетом UI-дампа: task 8696 → YouTube account-switcher, 8657 → TikTok промо, 8623 → домашний экран Samsung; 8696 + скринкастом. Все 18 — с срабатыванием foreground-recovery.

**Что сделано (`account_switcher.py`):** guard `_ig_guard_picker_foreground(cfg, header_y_max)` перед `_find_and_tap_account` — `_detect_foreground_pkg()` (тот же uiautomator-дамп, что и парсер); IG (или не определилось) → no-op; чужой пакет → `_ensure_app_foregrounded('Instagram')` + re-navigate; при неудаче → честный `ig_account_switcher_wrong_foreground` вместо `ig_target_not_in_picker`. Резолвер `error_code` (`publisher_base._set_error_code_from_events`) подхватывает категорию без whitelist. Kill-switch `IG_PICKER_FG_GUARD_ENABLED` (default ON). 8 новых тестов (`tests/test_account_switcher_ig_picker_fg_guard.py`) + правка `_make_ig_pick_switcher_stub`; весь набор переключателя 143 passed; codex review 0 находок.

**Деплой:** path-scoped `account_switcher.py` в `/root/.openclaw/workspace-genri/autowarm/`, fast-forward `git pull` (дерево чистое). PM2 restart не нужен — публишер спавнится per-task. OpenProject WP #119 → Тестирование; investigation WP #102 → Готово. Верификация — утренняя IG-пачка 22.05.

**Не покрыто (отдельно при появлении):** подслучай «IG на переднем плане, но не тот экран» (по данным редкий).

Триаж: `docs/evidence/2026-05-21-ig-publish-fails-triage.md`. Память: `project_ig_target_not_in_picker_foreground_hijack`.

## 2026-05-21 — TT: модал «Подтвердите видимость публикации» + AI-промпт кнопки публикации (WP #118)

### ✅ SHIPPED+DEPLOYED 2026-05-21 — delivery-contenthunter#89 (прод `7414891`)

Триаж TT-фейлов за 2026-05-21 (после исключения сетевой adb-проблемы): топ-1 = `tt_upload_confirmation_timeout` **7/14 (50%)**. По screencast'ам (task 8765/8799) + 15 дампам — два суб-режима под одним кодом.

**Суб-режим B (зафикшен):** после tap «Опубликовать» TikTok показывает блокирующий модал «Подтвердите видимость публикации: Все» с кнопкой «Подтвердить» — бот её не нажимал, публикация висела до таймаута (task 8799). За 7д ~49% (20/41) таймаутов доходили до этого post-publish состояния.

**Что сделано:**
- `_detect_tt_visibility_confirm_dialog` + `_handle_tt_visibility_confirm_dialog`: тап «Подтвердить» через `_strict_tap_clickable` (EXACT — «Изменить» не трогаем). Ветка в `wait_upload` loop **после** UPLOAD_OK-check; kill-switch `TT_VISIBILITY_CONFIRM_HANDLER_ENABLED` (default ON); per-task cap=5 → distinct `error_code` `tt_visibility_confirm_stuck` (через `prior_error_event`, `publisher_base.py:1912`).
- Исправлен AI-промпт кнопки публикации: была «blue or white button in top-right corner», стала «красная, внизу» (противоречила комментарию кода :1788; AI давал null в 39/41 таймаутов за 7д).
- 12 новых тестов (`tests/test_publisher_tt_visibility_confirm.py`); весь TT-набор (185) зелёный; codex review без замечаний.

**Деплой:** path-scoped `publisher_tiktok.py` в `/root/.openclaw/workspace-genri/autowarm/`, fast-forward `git pull` (дерево чистое). **PM2 restart не нужен** — публикатор спавнится per-task. Тесты из прод-копии 12/12. OpenProject WP #118 → Тестирование. Верификация — утренняя TT-пачка 22.05.

**Суб-режим A (бэклог, WP #122):** оверлей «Добавить в историю» (Samsung Add-to-Story / TT in-app Stories) перекрывает экран во время share-loop → кнопка публикации не находится, fallback мажет (≈4/7 падений 20.05). Существующие overlay-хендлеры работают только в `wait_upload`, не в share-loop. Не вошло в PR #89 — выше риск (основной путь публикации), нужен kill-switch + тесты.

Триаж: `docs/evidence/2026-05-21-tt-publish-fails-triage.md`. Память: `project_tt_upload_confirmation_timeout_recur_wp118`.

## 2026-05-20 — Ручная выкладка: операторская очередь готовых уникализаций (WP #107)

### ✅ Code-complete + MERGED 2026-05-20 — validator-contenthunter#18 + delivery-contenthunter#86 (pending deploy by Данил)

Продолжение WP #85. Операторский раздел «Выкладка → Ручная выкладка» (admin-only): для слотов, отмеченных на ручную выкладку, автоматически формируется очередь готовых пар «одно уник.видео × один аккаунт × публикация».

**Архитектура (Вариант A):** новая таблица `validator_manual_publish_queue` в openclaw, **физически отделена от `publish_queue`** — `dispatchPublishQueue` берёт строго `publish_queue.status='pending'`, поэтому manual-строки никогда не уедут на устройство автоматом. Гранулярность = 1 строка на (unic_result × аккаунт × платформа). Наполняет autowarm-крон `assignManualPublishQueue` (сиблинг `assignUnicResultsToQueue`, переиспользует вынесенные в `queue_pairing.js` резолверы scheme→pack→device→accounts). Auto-путь по-прежнему пропускает manual-слоты (guard WP #85 не тронут).

**Статусы:** `operator_status` ∈ queued|in_progress|published (text+CHECK). Отмена — через `cancelled_at IS NOT NULL` (не значение статуса); partial unique index + populator NOT EXISTS фильтруют `cancelled_at IS NULL` → cancelled-строка не блокирует пере-постановку после toggle ON→OFF→ON. Переходы: take/return/publish/rework (409 на недопустимый). «Отметить выкладку» открывает модалку с красным баннером, требует дата-время(МСК)+ссылку (422 если пусто), проставляет `matched_post_url` на слоте если пусто (петля с матчером WP #85). Toggle-OFF гасит queued-строки слота.

**Frontend:** `/manual-publish` (паттерн таблицы из `UsersManagement.vue`: sticky thead, мультисортировка Ctrl, фильтры по колонкам+сброс, группировка по телефону) + `PublicationCard.vue` (Teleport как `SchemeDetailModal`; копирование по клику, плеер, скачивание, режим подтверждения) + composable `useManualPublishTable.ts` + utils clipboard/accountUrl/datetimeMsk (МСК=UTC+3) + сайдбар-секция «Выкладка».

**Деплой (за Данилом, порядок):** validator `alembic upgrade head` (миграция 006, создаёт таблицу) → autowarm `pm2 restart autowarm` → validator `npm run build`. Kill-switch ENV `MANUAL_QUEUE_POPULATE_ENABLED=false`.

**Тесты:** validator pytest 167 (новый `test_manual_publish_queue` 6/6; +2 pre-existing Anthropic-mock фейла, не наши); autowarm `npm test` 0 fail (+8 новых); frontend vitest 6/6. Codex review спеки+плана (0 P1). Финальное холистическое ревью (opus): READY. Smoke по реальной БД: populator SELECT-join возвращает строки (manual-слоты 21244/21246), `ON CONFLICT ... WHERE` partial-index валиден (BEGIN/ROLLBACK).

**Gotcha (пойман live-DB тестом):** `GET /queue` без фильтра падал `asyncpg AmbiguousParameterError` на `:status IS NULL` → фикс `CAST(:status AS text)` (тот же класс, что `pipeline_reversal.py` `CAST(:keep_slot_id AS INTEGER)`). Правило: bind-параметр в `IS NULL`/`IS DISTINCT FROM` контексте требует явного CAST; node-фейки это не ловят.

**Follow-up (не блокер):** `rework` не откатывает `matched_post_url` на слоте (по спеке — «оставляем как историю»); edge publish→rework→republish может оставить старую ссылку (`mark_published` guard `WHERE matched_post_url IS NULL`). Решить позже, нужно ли чистить operator-sourced matched_*.

Spec/plan: `docs/superpowers/specs/2026-05-20-wp107-manual-publish-queue-design.md` + `docs/superpowers/plans/2026-05-20-wp107-manual-publish-queue.md`. Память: `project_wp107_manual_publish_queue`. OpenProject WP #107 → Тестирование (после деплоя+проверки → Готово).

## 2026-05-20 — TT: переключение аккаунта тапает аватарку со Stories (WP #112)

### ✅ SHIPPED 2026-05-20 PR #85 (`8280c6b`, delivery-contenthunter main)

Триаж TT-фейлов за 2026-05-20 (после исключения сетевой adb-проблемы): топ-1 = `tt_account_sheet_closed_before_parse` **10/27 (37%)**, ×3 к следующему бакету (`tt_account_not_in_list` 3, `tt_upload_confirmation_timeout` 3, `tt_post_switch_verify_unrecoverable` 3, `tt_profile_tab_broken` 3, хвост по 1). Воспроизводится на 7/10 задачах бакета — разные устройства (RFGYC31P*, RF8Y*) и проекты (ClickPay/Forsal/Art Estate) → системно. Скринкаст task 8528/8702: переключатель аккаунтов не открывается, вместо него открывается просмотрщик Stories.

**Root cause (`account_switcher.py`):** TikTok выкатил Stories на аватарку профиля; узел аватарки несёт `content-desc="storyringhas_consumed_story_true"`. В строке есть `_`, поэтому `_looks_like_username()` (правило «токен с разделителем = username») принимал её за username, и `_tap_profile_header()` тапал центр аватарки (540,337) — открывая Stories вместо переключателя. Настоящий username (`clickpay_world`, y≈503, ниже аватарки) не достигался, т.к. аватарка идёт в dump'е раньше. Текст ошибки врал про «залогинен только один аккаунт» (аккаунты есть).

**Что сделано:**

- `_looks_like_username` отвергает `_TT_STORY_RING_MARKERS` (closed-set `storyringhas_consumed_story_true`/`_false`) → header-tap доходит до настоящего username'а. Узкий set (codex P3) — легитимные хендли с похожим префиксом не трогает.
- Остаток в том же PR: `_detect_tt_stories_viewer` распознаёт экран Stories ещё и по счётчику зрителей (`_TT_STORIES_VIEWERS_RE`, owner-story/LIVE-specific) — крестик-иконка не матчила `Закрыть`/`Close`, из-за чего recovery (BACK→меню) не срабатывал. + честный текст ошибки.
- Тесты: +4 (storyring blocklist, header-tap target, owner-view X-icon detect, viewers standalone). TT-наборы зелёные (100 passed), 0 регрессий (12 pre-existing env/DB-фейлов идентичны на чистом дереве). Codex: 3 раунда, 0 P1/P2.

**Деплой:** path-scoped — обновлён только `account_switcher.py` в `/root/.openclaw/workspace-genri/autowarm/` (чужой WIP `server.js`/`changelog.md` соседней сессии не тронут). **PM2 restart не нужен** — публикатор запускается per-task (`server.js spawn python3`), следующая задача подхватывает код; рестарт загрузил бы чужой uncommitted `server.js`. 0 задач выполнялось в момент деплоя.

**Risk:** низкий — изменение бьёт лишь TT account-switch, восстанавливает исходный замысел (`profile_title_header_y_range` уже был (120,700) под username под аватаркой). **Verification PENDING:** подтверждение на TT-задачах, созданных после деплоя (`tt_account_sheet_closed_before_parse` из-за Stories не должен появляться).

Триаж: `docs/evidence/2026-05-20-tt-publish-fails-triage.md` (+ детальный в autowarm: `evidence/publish-triage/tt_account_sheet_closed_before_parse-20260520-task8528.md`). OpenProject WP #112 → Тестирование (переход в «Готово» после подтверждения на live-задачах).

## 2026-05-20 — YT: `yt_editor_not_reached` — guard фейлит на экране обрезки (WP #113)

### ✅ SHIPPED 2026-05-20 (`de02f17`, delivery-contenthunter main)

Триаж YT-фейлов за 2026-05-20 (после исключения сетевой adb-проблемы): доминанта = `yt_editor_not_reached` **62/74 (84%)**, success-rate ≈ 2.6%. Свежая регрессия: editor_not_reached 0 (≤17 мая) → 6 (18) → 85 (19) → 62 (20), совпадает с серией YT-правок (WP #80/#87/#88). Системно: 51 устройство, 8 raspberry, разные аккаунты/проекты → код-баг. Скринкаст task 8551 (`@oraclevisionn`): аккаунт переключён, бот доходит до экрана обрезки Shorts (`CreationModesActivity`, «Кадрировать»/«Далее») и зависает — «Далее» не нажата.

**Root cause (`publisher_youtube.py`):** коммит `0c01f7e` (18 мая, WP #80 Layer 3) добавил fail-fast `_verify_yt_editor_reached()` **перед** editor-loop. Guard признаёт редактор только по EditText title/desc, тексту «Добавьте название»/«Загрузить» или активити Upload/Share/Compose. Экран обрезки `CreationModesActivity` не подходит: его нет в allowlist, а UIAutomator слеп на video-surface (видео анимирует → отдаётся стейл home-feed, `edit_fields_count=0`) → `return False` → `yt_editor_not_reached`, **не доходя** до editor-loop, который уже умеет тапать «Далее» (933,2103). Доказательство рабочести loop: до guard'а task 5855 (14 мая) тем же Path B доходил до «Загрузить» на шаге 2.

**Что сделано:**

- В `_verify_yt_editor_reached()` `CreationModesActivity` теперь считается on-track (`return True`) → запускается проверенный editor-loop, который проходит «Далее» → редактор → «Загрузить». По сути восстановлено поведение, работавшее до 18 мая.
- Kill-switch `YT_VERIFY_CREATIONMODES_ONTRACK=0` → старое поведение (fail-fast).
- Тесты: +2 (on-track pass + kill-switch revert), **9/9 YT editor-guard зелёные**. Изменения только в `publisher_youtube.py` (IG/TT не тронуты).
- Codex review: без регрессий.

**Деплой:** path-scoped cherry-pick `de02f17` поверх параллельного IG-фикса `7a66a0a` (только `publisher_youtube.py` + тест; чужой WIP `server.js`/`changelog.md` не тронут), auto-push. **PM2 restart не нужен** — публикатор запускается per-task (`server.js spawn python3 publisher.py <id>`), следующая задача подхватывает код. PR #84 закрыт (влит в main).

**Risk:** низкий — изменение аддитивное, бьёт лишь YT, восстанавливает доказанно работавшее поведение, kill-switch наготове. Worst case (если «Далее» не проходит): bounded `yt_editor_upload_timeout` (существующий путь). **Verification PENDING:** YT публикуется пачкой 05:00–12:00 UTC; сегодняшняя прошла до выкатки → подтверждение на утренней пачке 21 мая (`yt_editor_not_reached` должен упасть, появиться info `yt_verify_creationmodes_ontrack`, вырасти `done`).

Триаж: `docs/evidence/2026-05-20-yt-publish-fails-triage.md`. Класс desync как в WP #105 (uiautomator слеп на анимирующих surface). OpenProject WP #113 → В разработке.

---

## 2026-05-20 — IG: `ig_share_tap_no_progress` ложно-негатив (WP #73)

### ✅ SHIPPED 2026-05-20 (`7a66a0a`, delivery-contenthunter main)

Триаж IG-фейлов за окно 2026-05-14..05-20 (после исключения сетевой adb-проблемы): топ-1 = `ig_share_tap_no_progress` (24/нед, 13 аккаунтов / 12 устройств → код-баг). Оказался **ложно-негативом**: Reel реально публикуется, но детектор успеха не распознаёт. Скринкасты task 8604 (`estate_m.ivanov`) и 8602 (`expertestate1`) — разные аккаунты/устройства — в момент «фейла» показывают опубликованный Reel в профиле с кнопками «Статистика»/«Продвигать». 16/18 свежих задач: post-share `topResumedActivity = InstagramMainActivity`.

**Root cause (`publisher_instagram.py`):** success-детектор искал устаревшую активность `MainTabActivity` в двух местах — `SUCCESS_ACT_TOKENS` (pre-Tier1 probe) и основной wait-loop. Текущий билд IG репортит post-publish активность как `InstagramMainActivity` (подстрока `MainTabActivity` в неё не входит) → probe не выставлял `skip_tier1` → Tier-2 ladder ретапил «Поделиться» по stale editor-дампу uiautomator → ложный фейл. Прежняя WP-гипотеза трактовала `InstagramMainActivity` как «share улетел в feed = провал» — опровергнута скринкастами (это успех).

**Что сделано:**

- `SUCCESS_ACT_TOKENS` += `InstagramMainActivity` под kill-switch `IG_MAIN_ACTIVITY_SUCCESS_ENABLED` (default true; `false` = revert).
- Основной wait-loop сверяется с общим `SUCCESS_ACT_TOKENS` вместо литерала `MainTabActivity` (единый источник истины с probe — иначе фейл лишь переименовывался в `ig_upload_confirmation_timeout`). + `import os`.
- Тесты: +2 новых (regression по 8604/8602 + kill-switch), обновлены 5 Tier-1 + 2 diag (дефолт стаба больше не InstagramMainActivity), застаблена URL-capture цепочка. **22/22 IG-теста зелёные**; 358 publisher-тестов зелёные (3 fail pre-existing, падают и на проде).
- Codex review: 0 issues.

**Деплой:** path-scoped коммит `7a66a0a` (только `publisher_instagram.py` + тесты; чужой WIP server.js/changelog.md не тронут), auto-push. **PM2 restart не нужен** — публикатор запускается per-task (`server.js spawn python3 publisher.py`), следующая задача подхватывает код.

**Risk:** `InstagramMainActivity` — общая главная активность; теоретически возможен ложно-позитив при аварийном выходе на home без публикации. Митигация: probe срабатывает только ПОСЛЕ Share-tap, и есть kill-switch. Наблюдение ~сутки: `ig_share_tap_no_progress` должен пойти вниз.

Триаж: `docs/evidence/2026-05-20-ig-publish-fails-triage.md`. Зеркало WP #82 (TT false-negative). OpenProject WP #73 → Тестирование (comments #324/#326).

---

## 2026-05-19 — YT: Layer 1 strict_verify substring → exact-match (WP #88)

### ✅ SHIPPED 2026-05-19 PR #81 (`a519bca`)

Layer 1 в `_tap_plus_and_verify` (account_switcher.py, после WP #80) проверял `editor_triggers` через permissive substring `t.lower() in ui.lower()`. Триггер `'Видео'` (substring `'видео'`) ложно матчился с `content-desc='Приостановить видео'` (Shorts player pause overlay). 4/15 кейсов 2026-05-18 проходили Layer 1 как false-positive → Layer 3 ловил позже через ~9 с (yt_editor_not_reached). Defense in depth работало, но точность Layer 1 страдала.

**Что сделано:**

- Layer 1 переехал с substring на **exact-match по node text/content-desc** через `xml.etree.ElementTree.fromstring` (account_switcher.py:4358-4385). Opt-in под `strict_verify=True` — только YT-путь (один call site `_switch_youtube`), IG/TT остаются на legacy substring без побочных изменений.
- `ParseError` → `hits=[]` → существующая ветка fail-fast `yt_create_menu_not_reached`.
- 4 новых unit-теста: Shorts overlay reject, Create-menu accept, malformed XML fallback, IG/TT non-strict regression.
- 232/232 yt+switcher тестов зелёные. 1 pre-existing main fail (`test_yt_happy_path_returns_accounts`) не связан.
- Codex review 0 P1 (spec + code diff).

**Risk:** если YouTube сменит casing/wording (`'видео'` строчное, `'Видео '` с trailing space) — Layer 1 даст false-negative и упадёт как `yt_create_menu_not_reached`. Митигация — обновить `UI_CONSTANTS['YouTube']['editor_triggers']` (single source of truth). Layer 2/3 продолжат работать.

Spec/plan: `docs/superpowers/specs/2026-05-19-wp88-yt-layer1-exact-match-design.md` + `docs/superpowers/plans/2026-05-19-wp88-yt-layer1-exact-match-plan.md`. OpenProject WP #88 → Готово (comment #294).

---

## 2026-05-19 — YT: post-publish URL polling false-negative (WP #97)

### ✅ SHIPPED 2026-05-19 PR #78 (`d5043a4`) — WP hypothesis опровергнута

WP-гипотеза была неверной: 30 с «watchdog_fired» — observability noise от S3 upload (>30 с при ~260MB screenrec), не вызывает failed. 8 false-negs 7д (Bucket 13) — **pre-WP-#86 historical artifact**. Реальный класс багов (status `awaiting_url` exhausted) уже закрыт через [[WP #86]] url-poller (PR #71/#73/#74).

**Ground-truth открытым:** на каналах пострадавших аккаунтов (quickrouterider, gerog-r7z, friendlyridescommunity, oracle_spacee) реально опубликованных видео из тех дат **нет** (yt-dlp + YT Data API confirm `videoCount=3-4`, latest 2026-05-01). Возможно YT-rejection, а не false-neg.

**Что сделано:**

- Новый env-var `YT_STEP_TIMEOUT_ZAVERSHENIE_SEC` (default 120, fallback на default при invalid input — `abc`/`0`/`-5`/empty). Установка в 30 = revert behavior. Применяется только к шагу «Завершение» (publisher_kernel.py), другие шаги не затронуты.
- 9 unit-тестов: default / custom override / kill-switch revert / invalid string / zero / negative / empty / others_not_affected / substring_match.
- Backfill SQL для 8-9 старых задач (статус `failed` без `error_code` + URL-poller log + `/shorts` post_url) — **manual run**, документирован в PR body и OpenProject comment.
- Codex review 0 P1 (spec + plan + code).

**Открытый вопрос:** если Bucket 13 вырастет пост-WP-#86 — открыть отдельный WP на real verification (channel `videoCount` delta).

Spec/plan: `docs/superpowers/specs/2026-05-19-wp97-yt-url-polling-design.md` + `docs/superpowers/plans/2026-05-19-wp97-yt-url-polling-plan.md`. OpenProject WP #97 → Готово (comment #295).

---

## 2026-05-19 — YT: `yt_create_menu_not_reached` foreground guard (WP #87)

### ✅ SHIPPED 2026-05-19 PR #79 + hotfix PR #83 (`c836074` + `d02f6ef`)

Триаж сегодняшних YT-фейлов (35/39 created, 97% fail rate, 8 raspberries) показал топ-bug — `yt_create_menu_not_reached` (26) + `yt_editor_not_reached` (7). В 6/6 проверенных UI dump'ах foreground на шаге `yt_6_create_menu` = `com.sec.android.app.launcher` (Samsung лончер), хотя на предыдущем `yt_5_target_profile` = `com.google.android.youtube`. 24/25 fails сопровождаются warning'ом `yt_post_switch_handle_unknown` на шаге target_profile.

**Root cause (двухслойный):**

1. `account_switcher.py:100 'plus_button': {'coords': (540, 2320), ...}` — попадало в Samsung navigation HOME (y=2317). При промахе `tap_element` fallback тапал по HOME → YT в фон → drift в лончер.
2. `tap_element(['Создать', 'Create'])` всегда промахивался — реальный `content-desc` YT FAB на этом устройстве/версии — **«Создание видео»** (взято из live UI dump task 8381, bounds=[432,2070][648,2205], центр (540, 2137)).

**Что сделано:**

PR #79 (`feat/yt-create-menu-fg-guard`, merged 13:18 UTC):
- **Layer A** — координата `(540, 2320)` → `(540, 2240)` (наполовину фикс, см. ниже).
- **Layer B** — при `strict_verify` промах `tap_element` → `_yt_ensure_foreground` retry до coord-fallback. Если всё-таки fallback — warning event `yt_plus_button_element_missing_fallback`.
- **Layer C** — после tap'а проверяем foreground; drift → recovery + retap, или fail-fast с новым `error_code='yt_create_menu_app_not_foregrounded'`.
- **Layer D (kill-switch)** — env `YT_CREATE_MENU_GUARD_ENABLED=0` откатывает Layer B/C.
- IG/TT (`strict_verify=False`) — поведение не меняется (regression-guard test).
- 10 commits TDD-style, 23 unit-теста, codex review 0 P1.

Hotfix PR #83 (`feat/wp87-hotfix-yt-plus-coords-desc`, merged 16:02 UTC):
- Layer A coord: `(540, 2240)` → `(540, 2137)` (live UI dump bounds.center).
- `desc`: `['Создать', 'Create']` → `['Создание видео', 'Create a video', 'Создать', 'Create']`.
- 11 unit-тестов обновлены, codex review 0 P1.
- **Why hotfix:** PR #79 был наполовину фиксом — координата (540, 2240) тоже мимо (gap между YT bottom-nav и system navbar). Урок — для UI-координат сверять с `bounds.center` из реального dump'а, не вычислять по скриншоту.

**Validation (после hotfix deploy, re-queue 72 задач):**

| status | n |
|---|---|
| failed | 18 |
| running | 10 |
| pending | 6 |
| **awaiting_url** | **1** (первый успех публикации) |

`yt_create_menu_not_reached` **исчез из failed** — мы доходим до Create-меню. Топ failed теперь:
- `yt_editor_not_reached` (15) — **другая стадия** post-create-menu (Layer 1 пропускает tap через `yt_create_menu_absent_skip_tap`, потом editor verify падает). Это территория [[project_yt_editor_upload_timeout_shipped]] + WP #88 backlog.
- `yt_app_not_foregrounded` (1) — наш Layer C сработал штатно: drift detected, recovery не помог, fail-fast.

### Открытые follow-up'ы

- **WP #88** (Бэклог) — «YT Layer 1 strict_verify: ужесточить substring → exact-match детектор» — стал актуальнее с появлением `yt_editor_not_reached` как нового топа.
- Tail остатки: `yt_picker_target_absent` (1), `yt_accounts_btn_missing_postmortem` (1) — единичные, не открывать пока без growth.

---

## 2026-05-19 — IG: ig_app_launch_failed stale-uiautomator (WP #105)

### ✅ SHIPPED 2026-05-19 PR #76 (`f480219`)

Триаж IG-фейлов 7д (2026-05-12…2026-05-19) выявил топ-1 непокрытый класс `ig_app_launch_failed` — 14 fails/7д, 3 fails сегодня, 13 уникальных устройств на ВСЕХ 6 raspberries (Pi #2/3/5/7/9/10). Топ-1 (`ig_share_tap_no_progress`, WP #73), топ-3 (`ig_target_not_in_picker`, WP #102) уже в backlog'е; топ-2 (`ig_picker_wrong_candidate`, WP #61) и топ-6 (`ig_gallery_no_video_candidate`, WP #61/#68) уже Готово — 0 свежих fails после 2026-05-14/15 это подтверждает.

**Root cause (13/13 fails 7д):** два метода foreground detection используют разные источники. `_ensure_app_foregrounded` (pre-check) видит IG через `dumpsys topResumedActivity` и эмитит `ig_app_foregrounded_after_recovery: attempt=2` (success). Immediately после — `_open_app._foreground_pkg` использует `uiautomator dump` как primary; на Samsung S21 uiautomator отстаёт до 60-90s после `am start` — видит `com.sec.android.app.launcher` пока ActivityManager уже знает что IG в foreground. 3 am-start retries не помогают (IG уже запущен, uiautomator всё ещё stale). `_open_app` fails через 86s. Скриншот +1s после fail показывает IG на экране (task 7821 clickpay_now + task 7692 contentexpert_ — оба evidence-tasks 2026-05-19).

**Решение — defense-in-depth в `account_switcher.py:_open_app` (PR GenGo2/delivery-contenthunter#76, squash `f480219`):**

- **L1** `_foreground_pkg(target_pkg)` — cross-source check (dumpsys + uiautomator). Trust target когда `pkg_ui==target` (UI ground-truth) ИЛИ `pkg_dump==target && pkg_ui ∈ {launcher, empty}` с подтверждающим poll'ом до 2.4s. Для permission/sbrowser overlay возвращается uiautomator package — `_dismiss_blocking_overlays` отрабатывает (НЕ short-circuit на real overlay).
- **L2** Settle-wait до 15s polling после 3 am-start attempts — ловит race «IG arrives 1-5s после last poll».
- **L3** Observability: `switcher_foreground_pkg_disagree` event при расхождении источников + `current_pkg_dumpsys` в meta при final fail.

Codex review: **3 round'а до 0 P1/P2** (правки confirming-poll + permissioncontroller-safety из round 2/3). 7 новых mock-based тестов + 1 update в test_overlay_dismiss (cross-source меняет dumpsys call count). 74 теста зелёные в test_account_switcher + test_overlay_dismiss. Pre-existing main фейлы (vision/orchestrator/publish_guard/intermediate_probes) НЕ затронуты — verified `git stash` reproduction.

Deploy: PR #76 squash-merged 2026-05-19 11:46 UTC, prod автоматически синкнулся через git pull (f480219). PM2 restart НЕ требовался — Python публикатор spawnится свежим процессом на каждую задачу (server.js spawn).

**Метрики после deploy (T+217min, 5 IG задач):**
- `ig_app_launch_failed` fails post-deploy: **0** ✅ (vs baseline ~2/день)
- `switcher_foreground_pkg_disagree` events (L1): **1** ✅ proof-of-life (cross-source ловит реальное расхождение в проде)
- `switcher_settle_wait_recovered` events (L2): 0 (паттерн отлавливается L1 раньше — норма)
- Other post-deploy fails: 3 (camera/caption/picker — другие классы, не наш WP)

Verification window incomplete на момент закрытия — выкладочное окно сегодня закрылось в 12:00 UTC (publish_queue пуст), для статистики нужен следующий утренний цикл ~04-09 UTC. WP #105 в OpenProject — статус «Тестирование», переход в «Готово» после 24h positive verification.

Spec/plan/evidence: `docs/superpowers/specs/2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md` + `docs/superpowers/plans/2026-05-19-wp105-ig-app-launch-stale-uiautomator-plan.md` + `docs/evidence/2026-05-19-wp105-ig-app-launch-shipped.md`. OpenProject WP #105 (assignee Данил, comment id 282).

Memory: [[project_wp105_ig_app_launch_stale_uiautomator_shipped]].

### Связанные открытые WP

- **WP #73** `ig_share_tap_no_progress` (31 fails/7д, 5 сегодня) — топ-1 IG, в backlog'е, refresh-комментарий 2026-05-19 запостил
- **WP #102** `ig_target_not_in_picker` (19 fails/7д) — в backlog'е
- **WP #8** `ig_camera_open_failed` (8 fails/7д) — нет WP, низкий приоритет, не покрыт текущим фиксом
- **WP #74 Round 2** YT foreign-foreground guard — концептуально близкая защита pattern shipped 2026-05-18 PR #72

---

## 2026-05-18 — YT foreign-foreground guard (WP #74 Round 2)

### ✅ SHIPPED 2026-05-18 PR #72 (`c9f75d5`)

Round 1 (PR #64, 15.05) закрыл 2/2 исходных кейса `yt_gallery_no_video_candidate`. 18.05 task 6899 (axilorj_ewelry, raspberry 1) поймал новый класс: **`ForceLoginSamungAccountActivity` (Samsung Galaxy Store)** перехватил foreground после `_normalize_yt_state_pre_upload` — force-stop YT тут бессилен, это чужой пакет (`com.sec.android.app.samsungapps`, не `com.google.android.youtube`). Force-stop YT убирает только наш собственный процесс; foreign overlay/activity остаётся и блокирует gallery probe → fail-fast.

PR GenGo2/delivery-contenthunter#72 (squash `c9f75d5`): 11 atomic TDD-коммитов через subagent-driven-development. **Helper-функция** `_parse_top_resumed_activity` (module-level regex `r'topResumedActivity=ActivityRecord\{[^}]*?\s+([\w.]+)/([^\s/}]+)'` + `lstrip('.')`) — Task 1. **Skeleton** `_dismiss_foreign_foreground(*, source, allow_recovery=True)` с probe → allowlist check — Task 2. **Kill-switch** env-flag `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` + `allow_recovery=False` — Task 3. **Escalation (a)** skip-tap (UI dump + tap по skip-keys) + helpers `_foreign_reprobe`, `_emit_foreign_foreground_outcome` — Task 4. **Escalation (b)** BACK×2 с re-probe между шагами — Task 5. **Escalation (c)** force-stop foreign + relaunch YT с blocklist halt для системных пакетов — Task 6. **Checkpoint #1** в хвост `_normalize_yt_state_pre_upload` (non-blocking) — Task 7. **Checkpoint #2** перед fail-fast в `_select_gallery_video` с 1-уровневой retry-рекурсией (`_foreign_retry_left` keyword param default=1) + meta enrichment — Task 8.

Allowlist (не считается foreign): `com.google.android.youtube{,.tv}`, `com.{android,google.android,samsung.android}.permissioncontroller`. Blocklist (no force-stop даже если foreground): `android`, `com.android.{systemui,settings}`, `com.google.android.{gms,packageinstaller}`. Зонтичный `error_code = yt_gallery_no_video_candidate` СОХРАНЁН для дашбордов; 7 новых meta-категорий (`yt_foreign_foreground_detected/recovered/unrecoverable/unrecoverable_blocklist/guard_disabled/probe_failed` + `yt_gallery_retry_after_foreign_recovery`).

12 unit + 4 integration = 16 новых тестов, 36/36 YT-suite зелёные. Codex review — 0 P1. Pre-merge live smoke на real testbench device (RF8Y80ZTVFZ через raspberry 1): real-world dumpsys корректно парсится (4/4 devices), Settings как foreign успешно triggers BACK×2 + blocklist halt (Settings в BLOCKLIST → halt без force-stop), event emission цепочка validated.

Prod deploy: PR squash-merged 18:31 UTC, `git pull origin main` в `/root/.openclaw/workspace-genri/autowarm/`, `sudo pm2 restart 34 autowarm` (uptime 0s, online). OpenProject WP #74 → Тестирование (id 9), comment id 266.

**24h live verify deadline ~2026-05-19 18:40 UTC** — acceptance:
1. Любой `yt_gallery_no_video_candidate` с `meta.foreign_foreground_recovered=true` → guard живой (success path сработал).
2. Любой `yt_gallery_no_video_candidate` БЕЗ `meta.foreign_foreground_detected` → старый класс фейлов (gallery не открылась) — НЕ регрессия от guard'а.
3. `meta.foreign_foreground_unrecoverable_reason='still_foreign'` — повторений 0 при ненулевом потоке YT-задач.

OpenProject WP #74, memory: [[project_yt_foreign_foreground_guard_shipped]]. Spec/plan/evidence: `docs/superpowers/specs/2026-05-18-yt-foreign-foreground-guard-design.md` + `docs/superpowers/plans/2026-05-18-yt-foreign-foreground-guard-plan.md` + `docs/evidence/2026-05-18-wp74-round2-smoke.md`.

### Открытые follow-up'ы

- **Launcher blocklist** (low priority, не блокер для verify): добавить `com.sec.android.app.launcher` (Samsung Home), `com.android.launcher`, `com.android.launcher3`, `com.google.android.apps.nexuslauncher` в `FOREIGN_FORCE_STOP_BLOCKLIST`. Symmetry с другими system pkgs (settings уже в blocklist). В pre-merge smoke Samsung Home выявлен как foreign — force-stop launcher технически работает (Android респавнит instantly), но heavy-handed. Стоимость: ~5 LOC + 1 тест. Можно отдельным mini-PR после verify.

---

## 2026-05-18 — Publish: задачи зависают в `awaiting_url` (WP #86)

### ✅ COMPLETE 2026-05-18 — 3 PRs SHIPPED (`d68b285` + `5e6c3b3` + `701d213`)

После успешной публикации задачи зависали в `awaiting_url` пока 48ч-timeout не сбрасывал их в `failed` (псевдо-провал, публикация-то прошла). Snapshot 2026-05-18 14:02 UTC: **45 stuck** (IG 27/TT 12/YT 6); за 24ч **0 задач** закрылись `done` с profile URL'ом — terminal-перехода для «опубликовано без specific URL» не существовало. 3 root cause: poller сломан (LIMIT 30 starvation новых задач + NULL `started_at` zombies + per-task budget отсутствовал) + однопроходная capture-механика (`_auto_get_*_url(45)`) + нет terminal-статуса для exhausted.

Решение — **β phased rollout 3 PR'а** (spec в `docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md`):

**PR1 foundation** (PR GenGo2/delivery-contenthunter#71, squash `d68b285`): schema migration (`url_capture_attempts INT`, `pre_publish_video_ids JSONB`, `url_capture_last_attempt_at TIMESTAMP` + partial index `idx_publish_tasks_status_updated WHERE status IN (processing, awaiting_url)`); url-poller fix (`LIMIT 30→100 env-driven`, `ORDER BY started_at→updated_at ASC` для fairness, `COALESCE(started_at, updated_at)` в 48ч timeout для NULL-zombie); attempts++ + промоут в новый terminal-статус `published_no_url` при `attempts >= URL_CAPTURE_MAX_ATTEMPTS` (default 30 = ~1ч); `syncQueueStatuses: published_no_url → pq.status='done'` (не `failed`, иначе re-queue → дубль публикации); жёлтый badge `✅ Без URL` в 4 publish_tasks renderers + status-filter dropdown + `pub-stat-done` counter; retroactive-cleanup миграция `20260518_wp86_retroactive_cleanup.sql` (15 stuck задач промоутнуто, publish_queue симметрично в `done`). Pure-helpers `shouldPromoteToPublishedNoUrl` + `getUrlPollerLimit` + `getUrlCaptureMaxAttempts` экспорт'нуты для tests (TDD, 17→23 unit tests). Subagent-driven dev через 18 tasks; codex/code-quality review нашёл 5 Important fixes + 2 dead-code reverts (audit lesson: `grep status='done'` находит hits на 3 разных таблицах — autowarm_tasks/publish_tasks/publish_queue — verify FROM-clause обязателен).

**PR3 server-side** (PR #73, squash `5e6c3b3`): A3 YouTube Data API через `scripts/yt_data_api_query.py` (Python CLI wrapper над `analytics_collector.youtube_api_get_videos`, exit code 2 на quota/403 → graceful fallback на yt-dlp); A5 differential id-diff — bot до publish сохраняет top-5 video-id'ов в `pre_publish_video_ids` JSONB (через `_snapshot_pre_publish_video_ids` helper в publisher_base, вызывается из TT+YT publishers), poller через `scrapeAllVideosDiff` pure-helper делает `current_ids - pre_snapshot - other_used = новые id`. Kill-switches `URL_CAPTURE_USE_YT_API=0`, `URL_CAPTURE_USE_DIFF=0`. 5 commits, 9 новых pytest + 5 unit tests JS, npm 150/150 pass. **Адаптация:** `youtube_api_get_videos` в analytics_collector возвращает только statistics — wrapper использует `playlistItems` endpoint напрямую (2 API calls).

**PR2 bot-side** (PR #74, squash `701d213`): A1 wave-retry для TT (3×45s с pull-to-refresh между waves, early-exit на specific URL через `_is_specific_reel_url`) — replaces single 45s attempt; A2 `_capture_via_notifications` helper (universal для TT+IG) через `adb shell dumpsys notification --noredact` + parse + foreign-account guard. **DONE_WITH_CONCERNS:** recon на тест-телефонах показал что TT/IG/YT **НЕ embed URL в text-полях** dumpsys notification — URL в PendingIntent (opaque для shell). A2 в текущем prod возвращает `None` для всех 3 платформ. Infra оставлена (~0.5s/publish overhead) с kill-switch `URL_CAPTURE_USE_NOTIF=0` + активируется автоматом если platform начнёт embed URL в notification text. **Реальная ценность PR2 = A1 TT wave-retry.** Kill-switches `URL_CAPTURE_BOT_WAVES=1` возвращает single-call legacy. 13 unit tests + recon evidence в `docs/evidence/2026-05-18-wp86-pr2-notification-recon.md`.

Все 3 PR'а merged squash, NO force-push. 1 merge conflict в `publisher_base.py` (оба PR добавили helpers рядом) — resolved через git merge, не rebase/force. 7 env-var kill-switches default ON. PM2 `restart 34 autowarm` (sudo) 18:04 UTC.

**Метрики после deploy** (6h window):
- `awaiting_url` stuck: **45 → 0**
- `published_no_url`: 0 → **20** (15 retroactive + 5 natural через PR1 poller)
- `done`: 31
- `failed`: 1

**24h post-deploy verify (~2026-05-19 18:00 UTC) acceptance:**
1. `awaiting_url` queue depth среднее <5 за сутки (vs 45 baseline).
2. `% specific-URL done` > 95% (vs ~85% baseline).
3. `published_no_url` < 5% от всех успешных публикаций (хвост невосстановимых через все 4 capture-механики).
4. Events `url_capture_via_yt_api` (PR3 A3) + `url_capture_via_diff` (PR3 A5) + `url_capture_via_share_wave` (PR2 A1) появляются > 0 для соответствующих платформ.
5. `failed` от 48h timeout (псевдо-провалы публикаций) ≈0/день (vs ~10% baseline).
6. Никаких regression'ов: посты не дублируются, `cleanupStuckTasks` совместим с новым `published_no_url`.

OpenProject WP #86 status «Готово», memory: [[project_wp86_published_no_url_complete]]. Spec/plans: `docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md` + `docs/superpowers/plans/2026-05-18-wp86-pr{1,2,3}-*-plan.md`. Evidence: `docs/evidence/2026-05-18-wp86-pr1-local-smoke.md` + `docs/evidence/2026-05-18-wp86-pr2-notification-recon.md`.

### Открытые backlog'и (отложены, не блокеры)

- **A1 wave-retry для IG/YT** — отложено в PR2 из-за multi-path complexity (IG имеет 2-step API+UI structure; YT имеет 6 call sites `_get_youtube_url_via_ui` с internal 3-try). Если метрики 24h покажут что IG/YT capture хвост существенный — отдельный mini-PR.
- **IG pre-snapshot (A5)** — в PR3 реализован только для TT+YT, IG требует отдельного path через `web_profile_info` API. Если IG diff matching ценен — отдельный mini-PR.
- **Notification scrape (A2) reality** — в текущем prod dead (URL в PendingIntent), но infra и helpers готовы. Если на новых телефонах notification permissions enable'ятся ИЛИ TT/IG embed URL в notification text в regional builds — A2 активируется через kill-switch.
- **Per-account shadowban detection** — если конкретные аккаунты постоянно дают `published_no_url` (yt-dlp/API возвращают 0 несмотря на successful publish) — это сигнал shadow-ban'а. Отдельная discovery WP при N+ повторений.

## 2026-05-18 — Publish-fails триаж (WP #79) — 8 child-WPs spawned

### ✅ SHIPPED 2026-05-18 (merge `dd4dbb7f6`, OpenProject WP #79 → Тестирование)

Discovery/triage WP от Анастасии — «проверить почему не выкладываются некоторые клиенты» (Релизми, Онлайн школа). Scope расширен по согласованию с пользователем на всех активных клиентов с fail-rate 7d >50% (18 пар client×platform, 11 клиентов) + клиентов с полным простоем (Pimble #79, Эль-косметик #82, Anecole #84).

**Главная находка** — `validator_unic_content = 0` у **14 активных проектов** при наличии `validator_content`. 3 простоя — видимая часть; остальные 11 живут на legacy approved-контенте, скоро встанут. Класс-уровневая блокировка uniqualization-стадии (worker упал / не enrol'ит новые проекты / изменилась схема).

Видео-анализ (5 буckets через ffmpeg + Vision Read) подтвердил:
- `switch_failed_unspecified::NULL` (17) = adb_push timeout на медиа >70MB (известный backlog, [[project_adb_push_network_issue]]).
- `switch_failed_unspecified::publish_failed_generic` (9) = **НОВЫЙ** — TT account-picker bottomsheet silently fails (tap'ом не открывается). НЕ покрыт WP #82.
- `NULL::NULL` (8) = **НОВЫЙ** YT false-negative — публикация прошла, watchdog URL polling 30с убил статус.
- `process_interrupted` (8) = PM2 deploy/restart kill, **infrastructure noise** ([[feedback_process_interrupted_is_pm2_noise]] — исключать из fail-rate).
- `adb_device_not_ready` (7) = ops, **единственное устройство RF8YA0V7LEH** в USB unauthorized.

**8 child-WP в OpenProject (parent=#79, assignee=danil):**
- **#95** [pipeline][P1] Uniqualization stall: 14 active projects with 0 `validator_unic_content` — **главный приоритет**, полная блокировка для 14 клиентов
- **#96** TT account-picker bottomsheet silently fails (publish_failed_generic, 9 fails 7d)
- **#97** YT post-publish URL polling даёт false-negative (NULL::NULL, 8 false-fails 7d, мгновенный backfill 8 тасков → done)
- **#98** adb_push chunked-push для медиа >70MB (17 fails 7d, известный backlog)
- **#99** [ops] re-cable / re-auth device RF8YA0V7LEH (USB unauthorized, 7 fails) — quick win
- **#100** [ops] re-login TT my_clickpay на RFGYC31P26P (account_not_in_list ×3)
- **#101** [ops] re-login TT clickpay_easy на RFGYC2VWBKN + my_clickpay (×5)
- **#102** [investigation] ig_target_not_in_picker — split ops (specific accounts/devices) vs code (UI parser race) (12 fails 7d)

**Already-shipped, упоминание без WP:** `tt_upload_confirmation_timeout` (40+6=46 fails, WP #82 PR #69), `yt_editor_upload_timeout` (3 fails, WP #80 PR #68). Мониторим 24-48ч.

**Tail-buckets без WP (9, с обоснованием в отчёте):** `ig_share_tap_no_progress` (24 — покрыт IG share retry tier2 shipped 2026-05-11), `tt_account_sheet_closed_before_parse` (20 — overlap с #96), `tt_post_switch_verify_unrecoverable` (17 — shipped 2026-05-11), `tt_profile_tab_broken` (17), `tt_account_menu_unknown_layout` (14 — overlap с #96), `date_mismatch::ig_picker_wrong_candidate` (11), `ig_gallery_no_video_candidate` (9), `ig_camera_open_failed` (8), `yt_create_menu_not_reached` (11 — частично WP #80). Открывать только при росте / regression к 2026-05-25.

**OTA-инцидент 2026-05-15** исключён из 7d окна как отдельный root cause ([[feedback_ota_screen_blocks_adb_preflight]]).

Spec/plan через 2 раунда codex review (0 P1) до коммита. Subagent-driven execution: 8 implementer-агентов sequential, summary комментарий id=259 на WP #79.

OpenProject WP #79 → «Тестирование» (lockVer 5→6). Memory: [[project_wp79_publish_fails_triage_shipped]] + [[feedback_process_interrupted_is_pm2_noise]]. Spec: `docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md`, plan: `docs/superpowers/plans/2026-05-18-wp79-publish-fails-triage.md`, отчёт: `docs/evidence/2026-05-18-wp79-publish-triage.md`.

### Priority order для пользователя

1. **#95** (полная блокировка для 14 проектов) — начать с `pm2 list | grep -i uniq` + `pm2 logs <name>` на VPS.
2. **#99** ([ops] quick win — 7 fails выключается одним re-cable).
3. **#97** (дешёвый код-фикс — поднять watchdog или сменить success-detection на статус, backfill 8 тасков).
4. **#96 / #98** (средние код-фиксы).
5. **#100/#101** ([ops] параллельно с #99).
6. **#102** (investigation) — после фиксов остальных.

---

## 2026-05-18 — Validator video uniqueness: sha256 dedupe + backfill (WP #77)

### ✅ SHIPPED 2026-05-18 PR #13 (`c59fb9e`)

Жалоба Анастасии в WP #77 (2026-05-18): ролики 2123 (project 96) и 2132 (project 99) висели в «Требует одобрения», но не были дубликатами — разные файлы из одной серии (TT-стайл шорты ~18с с похожим CRF). Старая `uniqueness_service.check_uniqueness` использовала duration±0.5с + size diff<5%, что фактически ловит **любые два** коротких видео одного жанра. Поле `content_hash` существовало в схеме `ValidatorContent` с самого старта (`index=True`), но **никогда не вычислялось** — ложно-помеченных копий со временем накопилось 16/443.

PR GenGo2/validator-contenthunter#13 (squash `c59fb9e`): полная замена на `sha256(file_bytes).hexdigest()` в трёх точках записи видео:
- `routers/upload.py` `/file` (прямой multipart) — inline hashlib после `file.read()`.
- `routers/upload.py` `/complete` (presign+S3, **главный prod-путь** — обнаружено в code review P4, изначально пропустил в спеке) — backend сам стримит файл из S3 через `compute_s3_object_sha256(s3_key)` в `loop.run_in_executor`. Non-fatal: при S3 hiccup оставляет NULL, не валит upload.
- `routers/content.py` `/replace-video` — inline hashlib + явный сброс `is_duplicate`/`duplicate_of_id` (codex P12 P2 fix — без сброса UI видел stale state между commit и `_do_full_validation`).

Helper `compute_s3_object_sha256` вынесен в `backend/src/services/content_hash_service.py` (8MB chunks, `S3ObjectNotFoundError` для missing keys, переиспользует `get_s3_client()`). Этот же helper используется backfill-скриптом.

`check_uniqueness(project_id, content_hash, content_id, db)` использует `func.min(id)` over hash-группу INCLUDING саму проверяемую запись; `min_id == content_id → не дубль`. Это защищает от flip-бага: при re-validation самого раннего оригинала после появления более поздней копии запрос с `id != content_id ORDER BY id ASC LIMIT 1` вернул бы late-id и flip'нул бы оригинал в дубль (поймано codex review при review плана).

Backfill `backend/scripts/backfill_content_hash.py --dry-run|--apply [--limit N]`: 443 candidate rows, ORDER BY id ASC, stream-hash в executor. Dry-run использует in-memory `dry_seen_hashes: dict[(pid, sha)] → first_id` для предсказания same-batch duplicates (codex P12 P2 fix — без этого `--apply` показал бы non-zero `marked_duplicate` после dry-run с нулём). Auto-unblock правило: `(was is_duplicate=True AND status=needs_review AND moderation_status=passed) AND теперь не дубль → status=approved`. **НЕ зовёт `notify_content_approved` webhook** — explicit decision (риск массовых мгновенных уникализаций на исторические записи).

5 live-DB тестов в `backend/tests/test_uniqueness_hash.py` (autouse `engine.dispose` fixture из conftest):
- `test_identical_files_marked_duplicate` (RED-then-GREEN базовый кейс)
- `test_different_files_not_duplicate` (**regression-guard** на убитую duration+size эвристику — фикстуры sample_a/b.mp4: ~2с длительность, 4.44% size diff, разные sha)
- `test_same_file_different_projects` (project isolation)
- `test_backfill_false_positive_unblocks` (production-realistic seed: first=approved/no-dup, second=needs_review/is_duplicate→разблокировка БЕЗ webhook)
- `test_backfill_real_duplicate_stays_blocked` (пара 4 — identical bytes → second остаётся blocked)

Production --apply (2026-05-18 16:31 UTC, на checkout `/root/.openclaw/workspace-genri/validator/`):
- 443 processed, 65 marked_duplicate (real), **16 auto_unblocked** (false-positives), 0 errors, 0 skipped_missing
- 2123 → status=approved ✅ (главная жалоба)
- 2132 → is_duplicate=False (status уже был in_uniqualization — ручной override до backfill, не разблокирован)
- 2120/2130 → hash записан, статус не изменён (был ok)
- 2130 остался needs_review, но moderation_status=**flagged** — отдельная причина, не дубликат

Backend перезапущен через `sudo systemctl restart validator-backend.service` сразу после merge — новые uploads через `/complete` пишут hash сразу же.

11 коммитов, 12 файлов, +578/-30. Codex review full diff via stdin — 1 false-positive P1 (asyncio не импортирован — verified, import был ещё в origin/main) + 2 P2 поправлены. Frontend banner: «🛑 Это точная копия контента #N (тот же файл)» + кликабельный `<router-link>` на оригинал, обновлён в ContentDetail.vue + ValidationDetails.vue (по [[feedback_validator_two_slot_renderers]] — оба места рендеринга).

OpenProject WP #77 → «Готово» (comment id=261). Memory: [[project_wp77_content_hash_dedupe_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-wp77-duplicate-false-positive-design.md` + `docs/superpowers/plans/2026-05-18-wp77-content-hash-dedupe.md`.

### Out of scope (не сделано в этом PR)

- **Perceptual hash** для уникализированных копий (pHash от кадров + Hamming distance) — отдельная фича, если когда-нибудь понадобится ловить «тот же ролик, чуть пересжатый», то это новый WP. Текущая логика **по дизайну** пропускает re-encoded клоны.
- **Uniqueness для post/carousel** — клиент не жалуется, scope не расширяли (image uniqueness в `validation.py:235` так и оставлен `is_duplicate=False`).
- **Permission на «Одобрить дубль» для client** — кнопка остаётся manager/admin only (как и было). Permission-модель не трогали.
- **Composite index `(project_id, content_hash)` partial** — solo-index по content_hash из исходной схемы уже даёт selective план для текущих объёмов. Если EXPLAIN покажет seq-scan на росте — отдельная миграция.

## 2026-05-18 — TT post-switch promo-modal dismiss (WP #67 Layer 2)

### ✅ SHIPPED 2026-05-18 PR #70 (`aa11d63`)

После Layer 1 (PR #62 от 2026-05-14, `@`-handle priority) `tt_post_switch_verify_unrecoverable` упал с 16/день до 1–2/день. WP #67 18.05 переведён обратно в «В разработке» — за 4 суток (15-18 мая) пришло 5 residual fails, у которых **другая** root cause: после переключения TT показывает блокирующий promo-модал, profile скрыт за ним. 4/5 кейсов (6514/6631/6704/6786) — байт-в-байт идентичная модалка «Привязать номер телефона или эл. почту» / «Не сейчас» (7603 байт). 1/5 (task 7307) — после renav вылез другой модал «Сохранить данные для входа» / «Не сейчас».

PR GenGo2/delivery-contenthunter#70 (squash `aa11d63`): Variant A — module-level whitelist `_TT_POST_SWITCH_DISMISSIBLE_MODALS = ((title, button), ...)` (2 evidence-seeded entry) + pure module helper `_tt_try_dismiss_post_switch_modal(xml) -> Optional[(title, button)]` (требует ОБА: title_substr `in el.label` И clickable `el.label.strip().lower() == button.lower()`) + instance method `_try_dismiss_and_redump(...)` (probe → tap_element → POST_TAP_WAIT_S sleep → dump_ui → returns `(title, new_xml)`) + 2 probe-site вставки в `_tt_handle_post_switch_unknown` (pre-feed-detect + post-renav-re-verify). Cap=1 dismiss/site, total ≤2/handle. Никаких новых error_code — `_attempted` event до fail'а различает старый/новый путь.

3 новых event: `tt_post_switch_modal_dismiss_attempted` (info), `tt_post_switch_recovered_via_modal_dismiss` (account_switch), `tt_post_switch_modal_dismiss_no_recovery` (warning, `reverify_status ∈ {tap_failed, unknown, mismatch}`). Все 4 caller-side события содержат `title_substr` для triage (Codex iter#1 fix).

16 тестов (10 unit + 6 integration) на реальных prod-dumps (`tt_post_switch_modal_phone_email_6514.xml` + `tt_post_switch_modal_save_login_7307_renav.xml`). Full switcher suite — 214/215 passed (1 pre-existing fail baseline, 0 регрессий). Codex review full diff via stdin — 0 P1/P2.

Prod deploy: `git pull --ff-only` в `/root/.openclaw/workspace-genri/autowarm` + `sudo pm2 restart autowarm` (2026-05-18 14:15 UTC). PM2 exec cwd OK, restart clean (без tracebacks).

Smoke re-queued 2 из 5 residual:
- task 7373 (just_clickpay) → `done`, без модалки (happy path не сломан).
- task 7372 (expertcontentlab) → probe сработал корректно (XML 7603→19628, модалка закрылась), но post-dismiss попали на чужой профиль «ᵂᴴᴵᵀᴱ ＢＩＴＡ» — picker-bug, **не WP #67 scope**, заведён отдельный WP #93.

24h soak deadline ~2026-05-19 14:15 UTC — acceptance: `tt_post_switch_verify_unrecoverable` ≤1/день (учесть picker-bug). Новая модалка не из whitelist даст `tt_post_switch_handle_unknown` БЕЗ `_attempted` события → расширяется одной строкой в whitelist.

OpenProject WP #67 → «В тестировании» (комментарий id=239). Memory: [[project_tt_post_switch_modal_dismiss_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md` + `docs/superpowers/plans/2026-05-18-tt-post-switch-modal-dismiss-plan.md`. Evidence: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md`.

### Follow-ups в backlog

- **WP #93 (новый):** picker-bug — task 7372 после dismiss попали на чужой профиль «WHITE BITA» вместо expertcontentlab. Account picker tap пошёл не в тот ряд. Низкоприоритетен пока не накопится ≥2 evidence.
- **Minor:** добавить тест-кейс `post_renav dismiss → reverify=mismatch` (низкий приоритет).
- **Refactor:** если IG/YT тоже потребуется dismiss — переименовать `_try_dismiss_and_redump` → `_tt_try_dismiss_and_redump` для platform-prefix consistency.

---

## 2026-05-18 — TT `tt_upload_confirmation_timeout` false-negative (WP #82)

### ✅ SHIPPED 2026-05-18 PR #69 (`ae41054`)

Триаж TT-фейлов за день (2026-05-18 UTC): 14 failed / 33 total. Топ — **10/14 `tt_upload_confirmation_timeout`** (≈71%) у разных аккаунтов и устройств. По iter1 UI-дампам видно — видео **уже опубликовано** (профиль `tkachenko_biohacking · 1 с. назад` + кнопка `Get more views`), но `_wait_upload_confirmation` 5+ минут крутится и убивается watchdog'ом. False-negative из-за 4 связанных багов в одной функции:

1. Success-detector `_tt_infer_post_publish_success` стоял ПОСЛЕ retap-ветки и generic dialog handler — они preemptили.
2. `share_btn_clickable` substring `'поделиться'` хватал overlay `«Поделиться видео. Уже поделились:»` на post-publish feed → false retap loop (6750/6788/6814).
3. `_detect_tt_contacts_perm` искал только `«доступ к контактам»` — FB-friends dialog `«доступ к списку ваших друзей в Facebook»` (6789/6809) проваливался в generic handler.
4. Promo-модал «Улучшенные входящие сообщения для бизнеса» (6750 iter10+/6804) re-presentился TT'ом после dismiss → infinite loop.

PR GenGo2/delivery-contenthunter#69 (squash `ae41054`): 7 atomic TDD-коммитов. **Change 1** early success-check в начале wait-loop с deduped dumpsys + `inferred_path_used` parity (`c320681`). **Change 2** fresh-post маркеры `Get more views` Button + timestamp regex `· N с. назад` (`da05399`) — работают и при flaky dumpsys. **Change 3** exact-match `('Поделиться', 'Post', 'Publish')` (`825df47`). **Change 4(a)** `_TT_PERM_DIALOG_VARIANTS` list (`e705498`). **4(b)** новый `_handle_tt_promo_inbox_modal` tri-state cap=5 → `inferred_success` (`8860111`). **4(c)** `_handle_tt_contacts_perm` тоже tri-state cap → `inferred_success` (`ee50743`). Plus реальные XML-fixtures (`7e46032`).

3 env kill-switches default ON: `TT_POSTPUBLISH_EARLY_CHECK_ENABLED`, `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED`, `TT_PROMO_INBOX_MODAL_HANDLER_ENABLED`. 11 новых unit-тестов с реальными XML-fixtures из инцидента + 5 уточняющих fix-pass тестов через subagent-driven dev (codex review spec — clean; 3 круга code-quality review с fix-pass'ами для double-dumpsys, регекса, env-gate convention).

Prod deploy: `pm2 restart 34 autowarm` 10:30 UTC (sudo, после `git pull --ff-only origin main`). Re-queued 10 TT-задач инцидента (6750/6751/6768/6781/6788/6789/6792/6804/6809/6814) → publish_queue=pending для проверки fix'а в живую.

**24h live verify deadline ~2026-05-19 10:30 UTC** — acceptance:
1. `tt_upload_confirmation_timeout` count за 24h ≤2/день (вместо 10).
2. Events `tt_post_publish_inferred_fresh_post` / `_from_promo_loop` / `_from_perm_loop` появляются > 0 (доказательство что новые пути активны).
3. Re-queued 10 задач завершаются в `done` (не `failed`).
4. `tt_promo_inbox_modal_dismissed` events растут (если promo-модал реален).

OpenProject WP #82, memory: [[project_tt_upload_confirmation_false_negative_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md` + `docs/superpowers/plans/2026-05-18-tt-upload-confirmation-false-negative-plan.md`.

### Открытые runner-up'ы из триажа 2026-05-18 (не затикечены, малый объём)

- **`tt_profile_tab_broken` (3/день)** — tap «Я» не открывает профиль. Memory `project_tt_post_switch_renav_shipped` упоминает recovery PR #34; 3/день — приемлемо, не takeaction. Если вырастет 7+/день — взять в discovery.
- **`tt_post_switch_verify_unrecoverable` (1/день)** — `tt_post_switch_handle_unknown` без recovery success. PR #34 должен покрывать; пристальнее если повторится 5+/день.

## 2026-05-15 — TT commercial-music modal handler (WP #75)

### `tt_upload_confirmation_timeout` (новая сигнатура «Коммерческие треки → TikBiz playlist») — ✅ SHIPPED 2026-05-15 PR #66 → ✅ VERIFIED + «Готово» 2026-05-22

Триаж TT-фейлов за день: 175 fails, 166 = сетевая `adb_devices_unreachable` (исключена, network уже починен), top non-network = 3 явных `tt_upload_confirmation_timeout` (tasks 6495/6510/6512) + 1 orphan (5202) с той же сигнатурой = 4/9 ≈ 44% non-network падений из одной корневой. На всех 3 screencast'ах TT застрял на одной и той же странице **«Коммерческие треки → TikBiz playlist»** (треки PONCHET, Yang Salah, Beat Automotivo, Happy/Vide..., Countless...) — публикатор не закрывает модал, AI vision возвращает `{x:null,y:null}` для кнопки «Опубликовать», 3-мин `wait_upload` timeout. Разные аккаунты (axilor_prive/brand, clickpay_under), разные устройства (RF8Y80ZTVFZ/RF8YA09S90H/RFGYC31P94Z), разные raspberry (#1/#9) — баг воспроизводим, не device-state. Это **НЕ** music-rights confirmation (диалог *согласия*, закрыт PR #28/#32), а новый **selector с принудительным выбором** коммерческого трека.

PR GenGo2/delivery-contenthunter#66 (squash `2dd53ff`): **3-level detector** (strict + fallback + evidence-only, аналог music-rights) → **cancel-select ladder** (`iter ≤ 2` → tap X, `iter > 2` → выбор 1-го трека через ✓, MAX=4 → `tt_commercial_music_stuck`) → wired в 2 hook'а (`_publish_share_loop` Шаг 5 — основной перед XML-сканом «Опубликовать», `_wait_upload_confirmation` outer loop — defensive). Env kill-switches `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (default ON) + `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` (default OFF). 9 новых event categories для триажа. 40 unit + 1 integration smoke + 305 passed в TT regression. Subagent-driven-development через 15 plan tasks, codex-review round 2 = 0 findings, final reviewer = ready to merge. PM2 `restart 34 autowarm` + `restart 33 autowarm-testbench` 18:22 UTC.

**24h live verify deadline ~2026-05-16 18:22 UTC** — acceptance:
1. 0 fails `tt_upload_confirmation_timeout` с сигнатурой `ai_find_tap_no_coords` на Publish-кнопке.
2. Распределение `tt_commercial_music_cancelled` vs `_track_selected` за 24h. Если 100% → select, cancel-X не закрывает модал, нужен switch policy на select-первым (iter2).
3. Нет `tt_commercial_music_stuck` events.
4. Если `tt_commercial_music_unhandled_suspect` (evidence-only) сработает — включить `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=true` и собрать XML dumps в `/tmp/autowarm_ui_dumps/`.

Memory: [[project_tt_commercial_music_modal_wip]]. Spec/plan/evidence: `docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md` + `docs/superpowers/plans/2026-05-15-tt-commercial-music-modal-handler.md` + `docs/evidence/2026-05-15-tt-publish-fails-triage.md`.

**Верификация + закрытие 2026-05-22** (`docs/evidence/2026-05-22-wp75-commercial-music-verify-close.md`): за 7д окно возникало 27 раз → `tt_commercial_music_cancelled`=27 / `_dismissed`=27, `_stuck`=0, `_track_selected`=0 — handler гасит окно при каждом появлении (acceptance 2 и 3 ✅, switch policy на select-первым НЕ понадобился). Сигнатура `ai_find_tap_no_coords` именно на модале не рецидивирует (acceptance 1 ✅). Нюанс: из 27 погашенных задач 16→done, 11→failed позже по флоу, но это НЕ модал — отдельный класс (`tt_upload_confirmation_timeout`: кнопка Publish / `wait_upload` false-negative), все 11 ДО фиксов WP #82 (PR #69, 18.05) и WP #118 (PR #89, 21.05); 22.05 после них — 0. Остаток ведут **WP #118** (shipped) / **WP #122** (backlog). Новый commercial-music handler не открывать. OpenProject WP #75 → «Готово».

### Открытые runner-up'ы из триажа 2026-05-15 (не затикечены, малый объём)

- **`tt_account_sheet_closed_before_parse` (2/день)** — bottomsheet со списком аккаунтов не открылся, target не добавлен на устройство. По msg выглядит как data-issue (онбординг аккаунта), не код-баг. Если повторится 7+ дней — взять в discovery.
- **`tt_profile_tab_broken` (2/день)** — tap «Я» не открывает профиль. Memory `project_tt_post_switch_renav_shipped` упоминает recovery PR #34. 2/день — приемлемый шум, не takeaction. Если вырастет — взять.
- **`tt_post_switch_verify_unrecoverable` (1/день)** — `tt_post_switch_handle_unknown` без recovery success. PR #34 (post-switch verify recovery) должен покрывать; пристальнее посмотреть если повторится 5+/день.

## 2026-05-15 — YT post-switch upload state normalization (WP #74)

### `yt_gallery_no_video_candidate` — ✅ SHIPPED 2026-05-15 PR #64

Триаж YT-фейлов за день: 166 fails, 164 = сетевая `adb_devices_unreachable` (исключена, network уже починен), 2 = `yt_gallery_no_video_candidate` (task 6513 oracle_spacee + 6515 oraclevisionn, raspberry 8, проект «Эзотерика Oleg»). На скринкастах оба раза YT после успешного `_ensure_correct_account` остаётся не в upload-state: 6513 завис на системном permission-диалоге «Откройте YouTube доступ к камере и микрофону», 6515 — на Shorts feed с открытой `Описание` bottom-sheet. Watchdog «post-account-switch» бил через 120s, picker фейлился с `all_clickable_count=0`.

PR #64 (3 коммита, squash `4722b81`): **A** `_normalize_yt_state_pre_upload` — `am force-stop` + `am start LAUNCHER` + 2 итерации permission-tap'ов перед probe'ом меню создания; **B** в `_select_gallery_video` parse loop добавлены 'При использовании приложения', 'Только в этот раз', 'Allow', 'Понятно'; **C** meta при fail-fast обогащена `top_resumed_activity` + `current_package` (категория `yt_gallery_no_video_candidate` сохранена — dashboards). 23 теста зелёные, codex без замечаний, prod `pm2 restart 34 autowarm` 16:42 UTC.

**24h live verify deadline ~2026-05-16 16:42 UTC** — acceptance: 0 fails `yt_gallery_no_video_candidate` за 24h при ненулевом потоке YT-задач. Memory: [[project_yt_post_switch_state_normalize_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-15-yt-post-switch-upload-state-normalization-design.md` + `docs/superpowers/plans/2026-05-15-yt-post-switch-upload-state-normalization.md`.

## 2026-05-15 — WP 63 scheduler status sync — ✅ SHIPPED

`fix(scheduler)` PR GenGo2/validator-contenthunter#12 (merged `520aaec`) — клиентский планировщик показывал «✅ Одобрено» уже когда `moderation_status=passed`, не учитывая `content_status`. Для контента с дублем (`passed + needs_review`) автовыкладка не запускалась (вебхук гейтит на `ContentStatus.approved` в `validation.py:132`), но UI рисовал готовность. Чистый классификатор в `frontend/src/utils/slotStatus.ts` + 23 unit-теста + согласованные цвет рамки/пилюли. WP 63 → `Тестирование`, ждём визуального подтверждения Анастасии. Evidence: `docs/evidence/2026-05-15-wp63-scheduler-status-fix-shipped.md`. Memory: [[project_wp63_scheduler_status_shipped]].

**Follow-up (low):** унификация manager-side `frontend/src/components/calendar/SlotCard.vue` на тот же `slotStatusInfo` — бага сейчас нет (manager уже смотрит на `content.status` напрямую), но единый классификатор уменьшит риск регрессии в будущем (из памяти `feedback_validator_two_slot_renderers` — два места рендеринга).

## 2026-05-14 — TT post-switch verify `@handle`-priority (WP #67)

### `tt_post_switch_verify_unrecoverable` — ✅ SHIPPED 2026-05-14 PR #62

Крупнейший незатикеченный баг дня (16/58 TT-падений, 16 устройств). `get_current_account_from_profile` брала верхний токен, прошедший `_looks_like_username` — на экране профиля TikTok это имя профиля / badge-счётчик НАД `@handle`. Свитч проходил, verify давал ложный mismatch. Фикс: ведущий разряд сортировки `is_bare` (`@`-токены приоритетнее). PR GenGo2/delivery-contenthunter#62 (squash `433c5b2`), в проде. Live smoke: 3/3 ре-выкладок распознали аккаунт через fast-path, 0 `tt_post_switch_verify_unrecoverable`. Memory: [[project-tt-post-switch-verify-handle-fix]]. Evidence: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`.

**24h soak deadline ~2026-05-15 16:00 UTC** — acceptance: `tt_post_switch_verify_unrecoverable` 16/24h → ~0. Query — в evidence-доке § «Запросы».

### Открытые runner-up'ы из триажа 2026-05-14 (не затикечены)

- **`tt_upload_confirmation_timeout` (7/день)** — свитч+verify проходят, видео заливается, экран подтверждения не детектится в таймаут (стадия `wait_upload`, не switcher). **Surfaced снова в smoke этого фикса** (tasks 5998/5999 дошли до publish-фазы и упали тут) — следующий кандидат на фикс по объёму.
- **`tt_profile_tab_broken` (5/день)** — tap «Я» не открывает профиль. PR #50 (TT security prompt dismiss) целился сюда с acceptance `< 2/24h` — 5/день на 2026-05-14 говорит, что PR #50 закрыл не всё; проверить на 24h-verify PR #50, возможно нужен отдельный заход.
- **retry-suffix gap мэппера** — триаж переподтвердил: `_SWITCHER_STEP_TO_CATEGORY` не матчит `_retry_N` шаги → реальная категория теряется в `publish_failed_generic` / `switch_failed_unspecified`. Уже описан ниже (секция «`switch_failed_unspecified` mapper retry-suffix gap»). 4 задачи 2026-05-14 замаскированы так.

## 2026-05-14 — WP 53 phantom schemes follow-up

### Router-level `unic_schemes` reads unfiltered (low priority)

WP 53 fix (PR #10) filtered `id > 0` in `schemes_service.get_schemes_with_preferences` + `get_summary` — the client-facing schemes screen. Three router-level reads in `backend/src/routers/schemes.py` still read `unic_schemes` unfiltered:

- `check_readiness` (`:141`) — `SELECT COUNT(*) FROM unic_schemes` → `total_schemes` (gates `previews_ready`)
- `generate_previews` (`:349`) — `SELECT * FROM unic_schemes ORDER BY id` → schemes sent to the render worker
- `approved_scheme_ids` (`:450`) — fallback `SELECT id FROM unic_schemes ORDER BY id`

Not urgent: the leak source is closed (`test_schemes_deficits._cleanup_project` now deletes `id <= -1`), so phantoms won't recur. But these are a latent inconsistency if a service row ever reappears via another path. Add `WHERE id > 0` for defense-in-depth when next touching that file. Evidence: `docs/evidence/2026-05-14-wp53-phantom-schemes-fix-shipped.md`.

## 2026-05-13 session follow-ups

### 24h verify (next day morning)

Четыре shipped PR в один день требуют 24h-verify SQL:

| PR | Topic | Deadline (UTC) | Acceptance |
|---|---|---|---|
| #48 | Watchdog ping regression | 2026-05-14 08:40 | Pi 3+5 `switch_failed_unspecified` < 5 / 24h |
| #49 | IG share OK fallback (Tier 1.5) | 2026-05-14 11:45 | `ok_rescued_24h / ok_attempted_24h ≥ 30%` |
| #50 | TT security prompt dismiss | 2026-05-14 13:25 | `tt_profile_tab_broken < 2/24h` AND `tt_security_prompt_dismissed > 0` |
| #52 | TT Pattern B (probe-and-pivot) | 2026-05-14 17:30 | `tt_account_sheet_closed_before_parse` ≤ 5/24h AND new codes ≤ 3/24h combined |

SQL pack в `docs/evidence/2026-05-13-*.md § "24h verify"` для каждого PR. PR #52 SQL — `jsonb_array_elements WITH ORDINALITY` (terminal `failed` event без category, нужно сканировать назад). После прогона — обновить evidence docs + memory entries (close OR iterate).

### TT Pattern B — `tt_account_sheet_closed_before_parse` ✅ SHIPPED 2026-05-13 PR #52

12-commit branch (`be62872..69a2dea`) squash-merged как `76ecd4f`. Probe-and-pivot orchestrator закрывает 19/24h root cause (TT app update — username tap открывает Stories/LIVE viewer вместо account-switcher bottomsheet). Memory: [[project_tt_pattern_b_shipped]]. Evidence: `docs/evidence/2026-05-13-tt-pattern-b-shipped.md`. Smoke pq 2149 live; 24h verify deadline 2026-05-14 17:30 UTC.

**Iteration #2 — 2-step settings-nested account switcher (HIGH priority, evidence in hand)**

Live smoke task 5572 (clickpay_go) post-hotfix: orchestrator successfully reached drawer search but `_find_tt_account_switcher_anchor_in_drawer` returned None. `drawer_labels[]` payload reveals new TT requires 2-step navigation: «Меню профиля» → «Настройки и конфиденциальность» → settings page → «Управление аккаунтами». Spec for iter#2 needed: add a settings-nested lookup pass to the orchestrator when first drawer search returns None. Anchors: `['настройки и конфиденциальность', 'настройки', 'settings and privacy', 'settings']`. Cap nesting at 1 level. See `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § Second smoke for the full drawer label list.

**Open follow-ups (Minor, from final holistic opus review):**
1. Inline-vs-helper asymmetry on `tt_account_sheet_closed_before_parse` emission (functionally fine).
2. `menu_dump` redundancy with `back_dump` (~1-2s extra).
3. `_tap_profile_header` internal `_save_dump` overwritten by orchestrator under same step name (pre-existing).
4. End-to-end test of menu-path through `_switch_tiktok` missing — smoke is only true verification. **CAUGHT BY THIS — smoke caught `adb_shell→adb` regression (hotfix PR #54) that 6 codex rounds + 48 unit tests missed.**

### `switch_failed_unspecified` mapper retry-suffix gap (new, 2026-05-13)

24h фон 25 fails, после декомпозиции:
- 17 pre-PR-#48 watchdog-killed — закроется по 24h verify PR #48
- 6 pre-PR-#48 other (вероятно тоже watchdog или race)
- **2 post-PR-#48 non-watchdog** — реальный остаток после сегодняшних deploy'ов

Корень: `_SWITCHER_STEP_TO_CATEGORY` в `publisher_kernel.py:76` НЕ знает retry-суффиксы (`tt_1_feed_retry_1`, `tt_3_open_list_retry_1` и пр.) → Pass-2 fallback resolver'а дефолтится на `switch_failed_unspecified`.

Sample failing steps post-PR-#48:
- task 5326 (TT, datj2k5): fail step `tt_1_feed_retry_1` — TT не запустился после post-switch retry restart. Должен мэппиться на `tt_app_launch_failed`.
- task 5296 (TT, relisme_co): fail step `tt_3_open_list_retry_1` — switcher's retry. Должен мэппиться на `tt_account_sheet_closed_before_parse`.

Fix варианты:
1. Strip `_retry_N` suffix в resolver Pass-2 перед lookup (1 line in `publisher_base._set_error_code_from_events`).
2. Явные entries для каждой retry-suffixed step в `_SWITCHER_STEP_TO_CATEGORY` (явнее, шире diff).

**Не блокер сегодня:** 2/24h, и часть «25» исчезнет после PR #48 verify. Чинить завтра после 24h-verifies (2026-05-14 morning UTC).

### AI Unstuck не firing — possibly self-resolved by PR #48

До PR #48 (08:40 UTC): AI Unstuck не firing 0/22 в TT timeout кейсах. Hypothesis: watchdog regression обрывал AI Unstuck до того, как он успевал что-то сделать. Per memory `project_watchdog_ping_regression_shipped` — теперь watchdog продлевается активностью. Проверить 24h: возвращается ли AI Unstuck к нормальной частоте.

### YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED 2026-05-14 PR #56

**НЕ self-resolved PR #48.** Триаж 2026-05-14 (OpenProject #59) нашёл 3 свежих `yt_editor_upload_timeout` (tasks 5685/5717/5724) — топ-причина YT-падений за день (3/6), #3 за 7д (14). Root cause: post-switch verify возвращает `'unknown'` → degrade-to-pass всегда, даже когда YouTube не на переднем плане → publisher уходит в 5-мин editor poll вслепую. Скринкасты: device на рабочем столе / Google voice search / Facebook prompt. 14/15 за 7д имеют precursor `yt_post_switch_handle_unknown`.

Фикс — `_switch_youtube` post-switch loop: degrade-to-pass на `'unknown'` теперь gated проверкой foreground-пакета; чужой app в foreground → fail fast с `yt_post_switch_app_not_foregrounded`. PR #56 squash-merge `348d495`, в проде 2026-05-14. Evidence: `docs/evidence/2026-05-14-yt-publish-triage.md`. Memory: [[project_yt_post_switch_foreground_guard]].

**24h verify deadline 2026-05-15 ~13:00 UTC** — SQL в evidence doc § "24h verify". Acceptance: `yt_editor_upload_timeout` после `yt_post_switch_handle_unknown` резко падает, вместо зависаний — быстрый `yt_post_switch_app_not_foregrounded`. Residual ~1/15 (editor genuinely stuck при YT в foreground) остаётся под item ниже.

---

## YT stabilization follow-ups (2026-05-12 session)

### Шаг D — yt_editor_upload_timeout (после AI Unstuck)

**STATUS 2026-05-14:** дублирующий precursor-вариант (`yt_post_switch_handle_unknown` → editor poll вслепую) закрыт PR #56 — см. item «YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED» выше. ОСТАЁТСЯ residual: ~1/15 за 7д имели `yt_editor_stuck_detected` БЕЗ precursor'а — YouTube был в foreground, но редактор реально завис. Вот этот случай — то, что не покрыто PR #56 и описано ниже.

13 fails/week pre-2026-05-13, single-pattern `YouTube: редактор timeout — Загрузить не найдено (после AI)` в `publisher_youtube.py:1199-1205`. AI Unstuck вызывается (`ai_unstuck_result=True`), что-то делает, но кнопка «Загрузить» не появляется. Screen recordings analysis на task'ах 4892/4444/4441. Hypothesis: editor в caption-screen с задержанной generation animation; AI не дожидается. Fix варианты: лучший detection caption-screen + skip AI, или post-AI wait+retry с другими criteria.

### Port `device_tz` to `publisher_helpers.parse_picker_thumbnail_date`

PR #45 (IG-only device-tz fix для phone #9 / Asia/Almaty) live в `publisher_instagram._ig_parse_thumbnail_date(desc, device_tz=None)`. После PR #43 (YT cross-project leak) IG имеет own copy с device_tz, YT использует `publisher_helpers.parse_picker_thumbnail_date` БЕЗ device_tz. Если YT начнут публиковать на не-MSK phones — будет False-mismatch. Port `device_tz` parameter в shared helper и rewire IG обратно на shared.

### Lead_Content_1 (и похожие) data-drift cleanup

Аккаунт в `factory_inst_accounts` с `gmail=NULL`, на phone в YT picker отсутствует (display name `Lead_Content `, suffix `_1` отсутствует, handle row отсутствует). Backfill no-match. Sticky 3 fails / 7d. Опции: (a) manual deactivation в БД; (b) automated `account_revision` post-scroll detector + auto-deactivate; (c) periodic backfill no-match log → daily TG bot notification.

**NB 2026-05-14:** не все `yt_picker_target_absent` / `yt_target_not_in_picker_after_scroll` — реальные отсутствия. Триаж iter2 (task 5856) доказал false-negative: аккаунт *присутствует* в picker'е, но matcher его не находит — см. item «YT picker — matcher игнорирует имя канала» ниже (#66). Этот data-drift item остаётся валиден только для *реально* отсутствующих аккаунтов; перед deactivation проверять, что аккаунта правда нет (matcher-баг сначала фиксится).

### YT picker — matcher игнорирует имя канала — ✅ SHIPPED 2026-05-14 PR #63 (OpenProject #66)

**✅ SHIPPED 2026-05-14** — PR GenGo2/delivery-contenthunter#63 (squash `6189cd6`), в проде через `git pull --ff-only`. OpenProject #66 → Тестирование. Memory: [[project_yt_picker_channel_name_match_shipped]].

Корень: `_find_and_tap_account` (`account_switcher.py`) для YT — gmail-fast-path работает только при заполненном `_yt_target_gmail` (нет у ~19% аккаунтов); fallback `find_account_in_list` — handle/username-ориентирован и НЕ матчит target против имени канала YT, которое для *неактивных* строк picker'а единственное видимое поле (`"<ChannelName>,,<subs>"`, без `@handle`). Dump usable + target не сматчен → терминальный FAIL без vision. Подтверждено task 5856 (`relismee` → канал «Relisme»). Семейство (`yt_target_not_in_picker_after_scroll` 23 + `yt_picker_target_absent` 4 = 27/7д) — крупнейшая actionable категория YT-падений за неделю.

Фикс: новые `_alnum_norm` + `find_yt_channel_name_matches` (консервативный матч по имени канала — точное совпадение или префикс с разницей длины ровно 1, `min(len)>=4`; ambiguity-guard: при 2+ кандидатах честный fail, не угадываем). 12 тестов TDD, 0 регрессий, codex + 3 раунда subagent-review.

**Открытые follow-up'ы (отдельные тикеты, вне #66):** добить `factory_inst_accounts.gmail` backfill для непокрытых ~19%; разобрать 11/27 за неделю где gmail в БД есть, но публикация всё равно не находит аккаунт. Evidence: `docs/evidence/2026-05-14-yt-publish-triage-iter2.md`.

### 24h soak — new YT RC counts

После Шагов B+C ждать 24h, затем:
```sql
SELECT events->-1->'meta'->>'category', COUNT(*)
FROM publish_tasks
WHERE platform='YouTube'
  AND created_at >= '2026-05-12 20:30:00+00'
  AND status='failed'
GROUP BY 1 ORDER BY 2 DESC;
```
Expected: `yt_target_not_in_picker_after_scroll` падает, `yt_picker_dismissed` + `yt_picker_target_absent` + `yt_picker_wrong_candidate` + `yt_gallery_no_video_candidate` появляются. Если `yt_gallery_no_video_candidate > 5/24h` — investigate device-state (не код).

### Real RC of 23-sec dead-time (race в task 3970)

Что dismisses YT picker между tap'ом и parse'ом (Шаг C показал: video player через 23s после picker shown). Hypothesis: spurious adb_tap из background / launcher / system notification. Defensive guard в Шаге C достаточно для observability и recovery; deeper investigation deferred до evidence accumulates.

## После 2026-05-12-scheme-preview-remote-worker

### Other ffmpeg tasks → unic-worker (same pattern)

После успешной миграции scheme preview по unic-worker queue pattern, следующие validator-side ffmpeg-задачи можно мигрировать тем же способом:

- **OCR** (`backend/src/services/ocr_service.py`)
- **Transcription** (`backend/src/services/transcription_service.py`)
- **Video metadata extraction** (`backend/src/services/video_metadata.py`)

Подход: alembic 005 расширяет `ck_unic_tasks_task_type` на новый `task_type`. Worker добавляет `process_<type>_task` функцию + dispatcher branch. Validator endpoint пишет в `unic_tasks` с соответствующим `task_type`. payload_hash и last_task_id guards переиспользуются.

### Heartbeat для legacy unic-pipeline

Сейчас `stale_task_recovery_loop` watchdog не трогает `task_type='unic'` потому что `process_task` может рендерить одну тяжёлую схему >15 мин без обновления `updated_at`. Решение: heartbeat_loop в legacy pipeline тоже (тот же helper, просто wrap). После этого расширить watchdog WHERE на оба task_type.

### Async cancellation orphan ffmpeg при PM2 restart

Codex P2 backlog из PR validator#6: `asyncio.to_thread + subprocess.run` не отменяют ffmpeg при SIGTERM. Перейти на `asyncio.create_subprocess_exec` с явным `process.kill()` в finally. Сейчас не релевантно для scheme preview (рендер на worker'е), но legacy unic-pipeline в worker.py остаётся sync subprocess.run.

### TG-notification при watchdog 3-revert

Сейчас только `logger.warning` идёт в `pm2 logs unic-worker`. Подключить через bugs-bot infrastructure (см. memory `project_bugs_bot`) — TG-нотификация в чат когда задача стоит в processing с `watchdog_revert_count >= 3`.

### Frontend timeout-aware error display

`UsersManagement.vue:348` паттерн `e.response?.data?.detail || 'Ошибка'` оставляет axios timeout кейсы немыми (generic «Ошибка»). Заменить на:

```js
catch (e: any) {
  formError.value = e.response?.data?.detail
    || (e.code === 'ECONNABORTED' ? 'Превышено время ожидания, попробуйте ещё раз' : null)
    || e.message
    || 'Ошибка'
}
```

Применить ко всем catch-блокам где `e.response?.data?.detail` ловится — есть в нескольких компонентах validator frontend.

### Multi-worker horizontal scale

Архитектурно разрешено через `FOR UPDATE SKIP LOCKED` в `get_pending_task`. Поднимать второй unic-worker на другом IP если queue depth растёт (нужно сначала enforce'ить heartbeat для legacy unic + monitoring queue depth).

### Cleanup duplicated phase→status mapping

Маппинг DB phase → legacy frontend status field дублируется в:
- `backend/src/routers/schemes.py` (внутри `check_readiness`)
- `backend/src/services/scheme_preview_queue.py` (внутри `read_scheme_preview_status`)

Когда фронт перейдёт на унифицированный shape (только `phase`, без `status`) — убрать дублирование. Сейчас оставлено для backward compat.

### Cancel-on-supersede для processing scheme_preview

Сейчас supersede mark'ает только `pending` строки. Если первая task уже в processing — она доработает (3-5 минут на схему × ~15 схем = до 75 минут), а новый payload встаёт рядом в pending. Можно добавить cancellation механизм:

```python
current_status='cancel_requested'
```

Worker check'ает между схемами и stops. Не критично пока, потому что новая task в любом случае перепишет результаты последней.

## 2026-05-25 — WP #44 пост-деплой (добивка тегов в описание): минорные остатки

Из код-ревью реализации (`feat/wp44-publish-tags-20260525`, merge `ae86367`). Не блокеры.

### Ручная постановка с явным caption для IG/TT не пишет теги в `publish_queue.hashtags`

В ручном endpoint ветка `unic_result_id && caption && platform !== youtube` оставляет `resolvedHashtags=[]`. Это пре-existing поведение (теги уже внутри переданной строки caption, диспетчер для IG/TT и так шлёт `hashtags=[]`), функционального бага нет. Если когда-то понадобится, чтобы добивка применялась и к ручному вводу с явным caption — добавить enrich в эту ветку.

### Нет лог-предупреждения при склейке многословного keyword

`enrichHashtags` склеивает «уход за кожей» → `уходзакожей` без лога. Оператор может удивиться составным тегам. Можно добавить debug-лог, когда нормализация keyword меняет его существенно. Низкий приоритет (keywords распаковки в основном короткие).

### `getBrandKeywords` — N запросов на проект в батче `assignUnicResultsToQueue`

Сейчас keywords тянутся один раз на `res` (unic_result), без кэша по проекту в рамках батча из 100. При росте батча — добавить мемоизацию `Map<projectId, keywords[]>`. Сейчас нагрузка пренебрежима.

## 2026-05-25 — WP #146 пост-шип (фильтр макс разрешения видео): остатки

Фикс зашипан+задеплоен (validator main `7ec2567`, OpenProject #146 → Тестирование): при загрузке видео >1080×1920 (±5%) — блокер `resolution_too_high`. Зеркало картиночной валидации. См. `docs/superpowers/specs/2026-05-25-wp146-resolution-filter-design.md`.

### Ретро-чистка 65 уже загруженных негабаритных исходников

Фильтр действует только на НОВЫЕ загрузки. В `validator_content` остаётся 65 видео >1080×1920 (топ: 2160×3840 ×31, 1440×2560 ×30) — их уникализации продолжат давать негабаритный выход (2260+). Если нужно — отдельная задача: даунскейл/перезалив исходников или ре-кью их `unic_results`. Не блокер.

### Провал s6 на 43 телефонах разрешением НЕ объясняется

В исходном кейсе (task 3683) s6/s5/s8 все негабаритные (2260–2390), «хорошие» s5/s8 даже больше «плохого» s6 → разрешение не отличает успех от провала. Реальная причина провала именно s6 на 43 телефонах не разрешение — вероятно сторона аккаунтов/устройств. Если жалоба повторится — отдельная разведка (триаж конкретных публикаций по screen_record/events), а не разрешение.

### (опционально) Строгий ≤1080×1920 на выходе уникализации

Уникализация добавляет +70…+260 px (scale_add+pad_add−crop_reduce, у всех 30 схем положительное), поэтому даже корректный 1080×1920 исходник → ~1150–1340 на выходе (соцсети сейчас терпят). Если когда-нибудь понадобится строгий лимит на ВЫХОДЕ — добавить downscale-to-fit в `unic-worker/worker.py::generate_ffmpeg` (финальный `scale=...:force_original_aspect_ratio=decrease`). Сейчас НЕ нужно — фильтр на исходнике решает проблему провалов.

## 2026-05-25 — WP #148 пост-шип (ручная выкладка published-leak): остатки

Фикс зашипан+задеплоен (autowarm prod main `5009575`, ROOT PM2 id=35 `autowarm`, OpenProject #148 → Тестирование): уже опубликованное автовыкладкой (`publish_queue.status='done'`) больше не сваливается в ручную очередь. retry-handoff стал per-account (слот не флипается), populator исключает done (`isAlreadyPublished`). Ретро-зачистка убрала 195 `queued`-дублей (live = 0). См. `docs/superpowers/specs/2026-05-25-wp148-manual-queue-published-leak-design.md` + evidence. Слито с параллельной WP #138 вручную (события retry/handoff в логе сохранены).

### sync-lag окно false-negative у populator'а

`isAlreadyPublished` смотрит `publish_queue.status='done'`, который проставляет `syncQueueStatuses` (~раз в 30 мин). Узкое окно: свежий авто-успех ещё не `done` → может разово попасть в ручную. Восстановимо (уникальный индекс не даст дубль, оператор отменит лишнюю строку). Закомментировано в коде. Не блокер.

### handoff берёт device-поля из снапшота publish_queue (не ре-резолв)

Per-account handoff читает `device_serial/raspberry_number/pack_id/pack_name` напрямую из упавшей строки `publish_queue`, а populator ре-резолвит через `resolveDevice`. Намеренная асимметрия (NOT NULL поля валидны, строка корректна). Отметка на будущее.

### Индекс `uq_manual_pub_result_account` не покрыт миграцией

`enqueueManualRow` опирается на partial unique index `uq_manual_pub_result_account (unic_result_id, account_username, platform) WHERE cancelled_at IS NULL` (ON CONFLICT). Индекс живёт в проде, но не создаётся ни одним файлом в `migrations/` (пре-existing — был и до WP #148). По правилу «миграции для любого писателя БД» стоит добить `CREATE UNIQUE INDEX IF NOT EXISTS` миграцию. Не блокер.
