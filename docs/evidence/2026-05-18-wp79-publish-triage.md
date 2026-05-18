# WP #79 — Publish-fails triage отчёт

**Дата:** 2026-05-18
**Окно:** 2026-05-11 — 2026-05-18 (7 дней, исключая OTA-инцидент 2026-05-15)
**Источник методологии:** docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md
**Spec scope:** все активные клиенты с fail-rate >50% за 7d ИЛИ с полным простоем (filled-слоты, 0 attempts)

---

## TL;DR

- **Системный uniqualization stall:** 14 активных проектов имеют 0 строк в `validator_unic_content`. Три из них (Pimble, Эль-косметик, Anecole) уже в полном простое; остальные 11 публикуют из legacy approved-контента и встанут, когда он кончится.
- **3 проекта в полном простое:** Pimble (19д), Anecole (11д), Эль-косметик (8д, очередь восстановлена сегодня) — все из-за зависшего uniqualization worker, не производящего approved-контент.
- **2 новых code-bug:** (a) TT account-picker bottomsheet не открывается при переключении — 9 fails ClickPay/Relisme/Art Estate; (b) YT false-negative watchdog — 8 успешных публикаций засчитаны как failed из-за тайм-аута polling URL.
- **2 ops-кейса:** device RF8YA0V7LEH USB unauthorized (7 fails); TT аккаунты my_clickpay/clickpay_easy не залогинены на устройствах (8 fails).
- **Шум от PM2-kill:** 8 tasks `process_interrupted` — не код-баги, нужно исключать из fail-rate метрик.
- **2 fix'а SHIPPED сегодня:** `tt_upload_confirmation_timeout` (PR #69 / WP #82) и `yt_editor_upload_timeout` (PR #68 / WP #80) — мониторим 24-48ч.

---

## Часть 1 — Высокий fail-rate (>50%, 7д)

18 пар (проект × платформа) с fail-rate >50% за OTA-отфильтрованное окно:

| Проект | Платформа | done | failed | fail_rate |
|--------|-----------|------|--------|-----------|
| Forsal | tiktok | 0 | 6 | 100% |
| BigKefBot | youtube | 1 | 9 | 90% |
| Ambassadori | tiktok | 1 | 4 | 80% |
| Content hunter | tiktok | 5 | 19 | 79% |
| Максим Иванов | instagram | 4 | 13 | 76% |
| Ambassadori | instagram | 2 | 5 | 71% |
| ClickPay | tiktok | 26 | 64 | 71% |
| Relisme | instagram | 10 | 23 | 70% |
| Парфюмерия | tiktok | 6 | 13 | 68% |
| Relisme | tiktok | 11 | 21 | 66% |
| ClickPay | instagram | 31 | 45 | 59% |
| Максим Иванов | tiktok | 7 | 10 | 59% |
| BigKefBot | tiktok | 5 | 7 | 58% |
| Content hunter | instagram | 13 | 17 | 57% |
| Парфюмерия | youtube | 10 | 12 | 55% |
| Content hunter | youtube | 11 | 13 | 54% |
| Feminista патчи для глаз | tiktok | 6 | 7 | 54% |
| Art Estate | tiktok | 17 | 19 | 53% |

### OTA-audit

OTA-инцидент 2026-05-15 оказал существенное влияние (>15% от raw-fails) практически на все пары. Наиболее затронутые (>40% fails убрано OTA-фильтром):

| Проект | Платформа | raw_failed | OTA_removed | % |
|--------|-----------|-----------|-------------|---|
| Александр Ткаченко | instagram | 4 | 4 | 100% |
| Forsal | youtube | 8 | 6 | 75% |
| Feminista патчи для глаз | youtube | 4 | 3 | 75% |
| Ambassadori | youtube | 9 | 7 | 78% |
| Forsal | tiktok | 12 | 6 | 50% |
| Ambassadori | tiktok | 9 | 5 | 56% |
| Ambassadori | instagram | 12 | 7 | 58% |
| Александр Ткаченко | tiktok | 5 | 3 | 60% |
| AXILOR Private | tiktok | 7 | 4 | 57% |

Вывод: fail-rate без OTA-фильтра был бы на 20-60% выше у большинства клиентов. OTA-фильтр обязателен для корректного триажа.

---

## Часть 2 — Полный простой (filled slots, 0 attempts)

| id | project | downtime | filled_slots | classification |
|----|---------|----------|--------------|----------------|
| 79 | Pimble | 19д | 2 | no_approved_content |
| 82 | Эль-косметик | 8д | 2 | approved_but_no_queue (очередь восстановлена сегодня) |
| 84 | Онлайн-школа Anecole | 11д | 5 | no_approved_content |

### Pimble (id=79) — 19 дней простоя

Простой с 2026-04-29. 2 активных пака (устройства 117/118, без end_date). Последняя генерация очереди — 2026-04-28 (слоты до 2026-04-25). Из 10 filled-слотов (2026-05-05 — 2026-05-14) все привязаны к контенту в состоянии `in_uniqualization` или `needs_review`. Единственный approved item (id=1922, updated 2026-05-05) привязан к слоту 2026-05-05, но queue-строки под него нет — producer не подхватил. 7 из 8 паков истекли 2026-05-04.

**Первопричина:** uniqualization worker не прогрессирует контент до `approved`; queue producer не подхватил единственный approved item при появлении.

**Состояние контента:** 6 `in_uniqualization`, 5 `needs_review`, 1 `approved`.

### Эль-косметик (id=82) — 8 дней простоя

Простой с 2026-05-10. 3 активных пака (устройства 21/22/42, без end_date). Последняя генерация очереди до инцидента — 2026-05-09 (слоты до 2026-05-10). Очередь была перегенерирована СЕГОДНЯ (2026-05-18): 54 pending items запланированы 2026-05-19 — 2026-05-24 — то есть producer восстановился, но почему был 9-дневный gap (2026-05-09 — 2026-05-18)? Filled-слоты 2026-05-12 и 2026-05-13 не имели queue-строк в окне инцидента. 19 из 24 items застряли в `in_uniqualization`.

**Первопричина:** uniqualization worker не прогрессирует контент; queue producer пропустил слоты или они заполнились после последнего dispatch-цикла.

**Состояние контента:** 19 `in_uniqualization`, 4 `needs_review`, 1 `approved`.

### Онлайн-школа Anecole (id=84) — 11 дней простоя

Простой с 2026-05-07. 3 активных пака (устройства 72/73/74, без end_date). Последняя генерация очереди — 2026-05-06. Все filled-слоты 2026-05-18 — 2026-05-22 (10 слотов) привязаны к контенту в `in_uniqualization`. Последний approved content — 2026-04-14 (id=1821), полностью израсходован исторической очередью. Ни одного approved item нет; 22 items зависли в `in_uniqualization`, 1 в `needs_review`.

**Первопричина:** чистый uniqualization bottleneck. Пакеты в порядке; контент не движется по pipeline.

**Состояние контента:** 22 `in_uniqualization`, 1 `needs_review`, 0 `approved`.

---

## Часть 3 — СИСТЕМНАЯ НАХОДКА: uniqualization stall у 14 проектов

SQL-запрос (свежий, 2026-05-18):

```sql
WITH ucc AS (SELECT project_id, COUNT(*) c FROM validator_unic_content GROUP BY project_id),
     vcc AS (SELECT project_id, COUNT(*) c FROM validator_content WHERE created_at > now() - interval '30 days' GROUP BY project_id)
SELECT vp.id, vp.project, vcc.c, COALESCE(ucc.c,0) FROM validator_projects vp 
JOIN vcc ON vcc.project_id=vp.id LEFT JOIN ucc ON ucc.project_id=vp.id
WHERE vp.active=true AND COALESCE(ucc.c,0)=0 AND vcc.c>0
  AND vp.project NOT IN ('Tatyana.demo','Ann.demo','demo for onboarding') ORDER BY vcc.c DESC;
```

**Результат — 14 проектов с 0 строк в validator_unic_content и активным контентом за 30д:**

| id | Проект | content за 30д | unic_content |
|----|--------|---------------|--------------|
| 82 | Эль-косметик | 24 | 0 |
| 85 | ClickPay | 23 | 0 |
| 84 | Онлайн-школа Anecole | 23 | 0 |
| 101 | Александр Ткаченко | 20 | 0 |
| 83 | Септизим | 18 | 0 |
| 96 | AXILOR Private | 15 | 0 |
| 87 | Forchil | 13 | 0 |
| 99 | Эзотерика Orakul | 13 | 0 |
| 79 | Pimble | 12 | 0 |
| 100 | Feminista патчи для глаз | 11 | 0 |
| 81 | Wanttopay | 11 | 0 |
| 102 | Юлия Сваровски | 10 | 0 |
| 74 | Парфюмерия | 3 | 0 |
| 112 | Аквабрайт | 2 | 0 |

**Интерпретация:** 3 проекта в полном простое (Pimble, Эль-косметик, Anecole) — видимая часть проблемы. Остальные 11 (ClickPay, Александр Ткаченко, Септизим, AXILOR Private, Forchil, Эзотерика Orakul, Feminista, Wanttopay, Юлия Сваровски, Парфюмерия, Аквабрайт) пока публикуют из legacy approved-контента. Как только он исчерпается — встанут аналогично. Проекты более старой обкатки (Relisme id=9, Content hunter id=53, BigKefBot id=60, Art Estate id=49) имеют unic_content и не входят в список — у них другие причины fail-rate.

**Гипотеза root cause:** uniqualization worker либо упал и не перезапустился, либо обрабатывает другой набор проектов, либо есть смена интерфейса/контракта (`validator_unic_content` пуста у всех новее-онбордованных проектов начиная с определённого момента). Требует P1-расследования.

---

## Часть 4 — Bucket-разбор (top-16, классифицированные)

### Bucket 1: `tt_upload_confirmation_timeout::tt_upload_confirmation_timeout` — n=40

- **type:** shipped (PR #69 / WP #82, 2026-05-18)
- **affected:** Forsal TT ×1, Ambassadori TT ×1, Content hunter TT ×5, ClickPay TT ×12, Парфюмерия TT ×4, Relisme TT ×5, BigKefBot TT ×5, Art Estate TT ×7
- **verified_rc:** TT upload-confirmation watchdog ложно засчитывал timeout; fix добавил early-success check + fresh-post маркеры + promo/perm handlers
- **child-WP:** SHIPPED — WP #82

### Bucket 2: `ig_share_tap_no_progress::ig_share_tap_no_progress` — n=24

- **type:** code-bug (не классифицирован ранее, требует расследования)
- **affected:** Максим Иванов IG ×8, Relisme IG ×1, ClickPay IG ×11, Content hunter IG ×4
- **verified_rc:** нет видеодоказательств в этом окне; гипотеза — share-кнопка зависает после tap (нет прогресса к следующему экрану)
- **child-WP:** TAIL — известный код-баг IG share, покрыт IG share retry tier2 (shipped 2026-05-11). 24 fails 7d за shipped-окном — мониторим, если не упадёт значительно к 2026-05-25, открыть отдельный WP на регрессию.

### Bucket 3: `tt_account_sheet_closed_before_parse::tt_account_sheet_closed_before_parse` — n=20

- **type:** code-bug
- **affected:** ClickPay TT ×13, Relisme TT ×1, Feminista TT ×3, Art Estate TT ×3
- **verified_rc:** TT account-picker sheet закрылся до того, как парсер успел прочитать список аккаунтов
- **child-WP:** TAIL — родовая связь с WP #96 (TT account picker bottomsheet silent fail). Возможно общий root cause — UI-timing race в TT account sheet. Открыть отдельный WP, если после фикса #96 эти 20 fails не уйдут.

### Bucket 4: `tt_post_switch_verify_unrecoverable::tt_post_switch_verify_unrecoverable` — n=17

- **type:** investigation (связан с WP #82 Layer patterns, но отдельный failure mode)
- **affected:** Forsal TT ×2, Content hunter TT ×1, Парфюмерия TT ×5, Relisme TT ×3, Максим Иванов TT ×4, Art Estate TT ×2
- **verified_rc:** не подтверждён; верификация профиля после switch falls через два retry
- **child-WP:** TAIL — post-switch verify recovery shipped 2026-05-11 (see project_tt_post_switch_verify-* в памяти). 17 residual fails 7d — мониторим, если не упадут к 2026-05-25, открыть регрессионный WP.

### Bucket 5: `tt_profile_tab_broken::tt_profile_tab_broken` — n=17

- **type:** investigation
- **affected:** Forsal TT ×1, ClickPay TT ×3, Парфюмерия TT ×1, Relisme TT ×7, Feminista TT ×3, Art Estate TT ×2
- **verified_rc:** нет; профиль-таб TT не открывается / не обнаруживается
- **child-WP:** TAIL — old known issue в TT-backlog. 17 fails 7d Relisme/Feminista/Art Estate TT. Не открываем новый WP — есть в общем TT-стабилизация backlog.

### Bucket 6: `switch_failed_unspecified::NULL` — n=17

- **type:** code-bug (известный backlog)
- **affected:** Content hunter TT ×5, Content hunter IG ×7, Content hunter YT ×5 (все — Content hunter)
- **verified_rc:** adb_push timeout на oversized media (>70MB). Screencast не запускался, т.к. watchdog срабатывал дважды (180s each), исчерпывал 1 relaunch retry. Никакого UI-взаимодействия не происходило.
- **child-WP:** **WP #98** — adb_push timeout на медиа >70MB (chunked-push backlog)

### Bucket 7: `tt_account_menu_unknown_layout::tt_account_menu_unknown_layout` — n=14

- **type:** code-bug
- **affected:** Forsal TT ×2, Content hunter TT ×2, ClickPay TT ×10
- **verified_rc:** TT account menu показал нераспознанный layout — парсер не смог найти известные UI-элементы
- **child-WP:** TAIL — связан с bucket 3 и WP #96 (общий UI-layout TT account drift). Отдельный WP только если после фикса #96 эти 14 fails не уйдут.

### Bucket 8: `ig_target_not_in_picker::ig_target_not_in_picker` — n=12

- **type:** investigation (mixed: ops + code)
- **affected:** Relisme IG ×5, ClickPay IG ×7
- **verified_rc:** частично ops (конкретные аккаунты/устройства не залогинены), частично code (UI picker race)
- **child-WP:** **WP #102** — ig_target_not_in_picker split investigation

### Bucket 9: `date_mismatch::ig_picker_wrong_candidate` — n=11

- **type:** investigation
- **affected:** Максим Иванов IG ×2, ClickPay IG ×9
- **verified_rc:** нет; picker выбирает неправильный медиа-файл по дате
- **child-WP:** TAIL — IG picker берёт не тот файл по дате. 11 fails 7d (ClickPay IG ×9). Sub-issue, открывать отдельный WP при росте >15.

### Bucket 10: `yt_create_menu_not_reached::yt_create_menu_not_reached` — n=11

- **type:** investigation (частично покрыто shipped WP #80)
- **affected:** Парфюмерия YT ×8, Content hunter YT ×3
- **verified_rc:** нет; create-меню YT не открывалось — предшественник yt_editor_not_reached
- **child-WP:** WP #80 SHIPPED покрывает yt_editor_not_reached; этот bucket требует доп. расследования

### Bucket 11: `ig_gallery_no_video_candidate::ig_gallery_no_video_candidate` — n=9

- **type:** investigation
- **affected:** Максим Иванов IG ×1, Relisme IG ×6, ClickPay IG ×2
- **verified_rc:** нет; IG gallery-picker не нашёл видео-кандидата
- **child-WP:** TAIL — 9 fails 7d, Relisme IG ×6. Sub-issue, общий с #102 (ig_target_not_in_picker family). При росте >15 — отдельный WP.

### Bucket 12: `switch_failed_unspecified::publish_failed_generic` — n=9

- **type:** code-bug (НОВЫЙ)
- **affected:** ClickPay TT ×5, Relisme TT ×3, Art Estate TT ×1
- **verified_rc:** TikTok account-picker bottomsheet не открывался после account switch (шаг tt_3_open_list). Устройство находилось на экране профиля clickpay_life; оба попытки (original + retry_1) находили usable XML, но bottomsheet никогда не появлялся. НЕ покрыт WP #82.
- **child-WP:** **WP #96** — TT account-picker bottomsheet silently fails (publish_failed_generic)

### Bucket 13: `NULL::NULL` — n=8

- **type:** code-bug (НОВЫЙ false-negative)
- **affected:** BigKefBot YT ×7, Relisme TT ×1
- **verified_rc:** YouTube публиковал успешно ("Публикация успешна: YouTube" залогировано, post-warm завершён), но статус засчитывался как failed из-за тайм-аута polling нового video URL (30s watchdog на шаге завершения). 7 из 8 — BigKefBot YT.
- **child-WP:** **WP #97** — YT false-negative: watchdog URL polling times out after successful publish

### Bucket 14: `process_interrupted::process_interrupted` — n=8

- **type:** noise (PM2 kill)
- **affected:** Content hunter TT ×1, Relisme IG ×4, Парфюмерия TT ×2, ClickPay IG ×1
- **verified_rc:** PM2 process kill (KeyboardInterrupt) mid-publish — не app/UI баг. Все 8 задач завершились через runtime interrupt, как правило в цикле deploy/restart.
- **action:** исключить из fail-rate метрик; не открывать WP

### Bucket 15: `ig_camera_open_failed::ig_camera_open_failed` — n=8

- **type:** investigation
- **affected:** Relisme IG ×2, ClickPay IG ×6
- **verified_rc:** нет; IG camera не открылась (либо неправильный режим, либо UI не ответил)
- **child-WP:** TAIL — 8 fails 7d, ClickPay IG ×6. Sub-issue, при росте >15 — отдельный WP.

### Bucket 16: `switch_failed_unspecified::adb_device_not_ready` — n=7

- **type:** ops
- **affected:** Ambassadori TT ×1, Content hunter TT ×1, Ambassadori IG ×1, Парфюмерия TT ×1, Content hunter IG ×1, Парфюмерия YT ×1, Content hunter YT ×1 — **единственное устройство RF8YA0V7LEH**
- **verified_rc:** ADB preflight hard-failed: устройство в unauthorized state (USB auth отозвана). Task прерван до любого UI-взаимодействия. Скринкаст не захвачен.
- **action:** ops — перекабелировать / re-auth RF8YA0V7LEH

**Skipped (tail) buckets — n<5, без классификации:**
`tt_account_not_in_list::tt_account_not_in_list` (5, ops), `yt_editor_not_reached::yt_editor_not_reached` (4), `tt_fg_drift_unrecoverable::tt_fg_drift_unrecoverable` (4), `tt_app_not_foregrounded::publish_failed_generic` (4), `switch_failed_unspecified::tt_profile_tab_broken` (4, code), `switch_failed_unspecified::ig_app_launch_failed` (3, code), `switch_failed_unspecified::tt_account_not_in_list` (3, ops), `yt_editor_upload_timeout::yt_editor_upload_timeout` (3, shipped), `ig_share_tap_no_progress::screencast_stop_failed` (2), `date_mismatch::screencast_pull_failed` (2), `ig_app_not_foregrounded::publish_failed_generic` (2), `NULL::screencast_stop_failed` (1), `tt_perm_dialog_stuck::tt_perm_dialog_stuck` (1), `ig_share_tap_no_progress::screencast_pull_failed` (1), `mediastore_top_mismatch::ig_picker_wrong_candidate` (1), `tt_share_activity_not_opened::tt_share_activity_not_opened` (1), `tt_drawer_tap_did_not_open_sheet::tt_drawer_tap_did_not_open_sheet` (1), `tt_profile_tab_broken::screencast_stop_failed` (1), `ig_gallery_no_video_candidate::screencast_pull_failed` (1), `ig_wrong_camera_mode::ig_wrong_camera_mode` (1), `date_mismatch::screencast_stop_failed` (1), `ig_caption_screen_not_reached::ig_caption_screen_not_reached` (1), `ig_gallery_button_not_found::ig_gallery_button_not_found` (1), `switch_failed_unspecified::screencast_stop_failed` (1, noise), `yt_target_not_in_picker_after_scroll::yt_target_not_in_picker_after_scroll` (1), `anchor_not_found::tt_account_switcher_unreachable` (1)

---

## Часть 5 — Shipped fixes (упоминание, WP не открываем)

- **`tt_upload_confirmation_timeout`** (40+6=46 fails за 7d) — PR #69 / WP #82 SHIPPED 2026-05-18. Мониторим 24-48ч. (+6 = bucket `tt_upload_confirmation_timeout::screencast_stop_failed` n=6, тот же error_code)
- **`yt_editor_upload_timeout`** (3 fails за 7d) — PR #68 / WP #80 SHIPPED 2026-05-18. Мониторим 24-48ч.

---

## Часть 6 — Шум (исключить из fail-rate метрик)

| Bucket key | n | Причина |
|------------|---|---------|
| `process_interrupted::process_interrupted` | 8 | PM2 restart kills, не app/UI баг |
| `switch_failed_unspecified::screencast_stop_failed` | 1 | cleanup artifact при switch |
| `NULL::process_interrupted` | 6 | аналогично PM2-kill (NULL error_code + process_interrupted category) |

Итого шума: ~15 tasks из общего пула fails. При расчёте агрегированного fail-rate рекомендуется фильтровать по `last_error_category NOT IN ('process_interrupted')`.

---

## Часть 7 — Per-client сводка

### Relisme (id=9) — instagram 70% / tiktok 66%

Главные RC:
- IG: `ig_share_tap_no_progress` (×1), `ig_gallery_no_video_candidate` (×6), `ig_camera_open_failed` (×2), `ig_app_launch_failed` (×3), `process_interrupted` (×4), `ig_target_not_in_picker` (×5)
- TT: `tt_upload_confirmation_timeout` (×5, SHIPPED), `tt_post_switch_verify_unrecoverable` (×3), `tt_profile_tab_broken` (×7), `switch_failed_unspecified::publish_failed_generic` (×3), `tt_account_not_in_list` (×1)

Основные проблемы: IG gallery/camera failures + TT multiple switch/profile issues. Unic_content отсутствует (14-list) — если legacy content кончится, встанет.

### Pimble (id=79) — полный простой 19д

Подробности в Части 2. Причина: uniqualization stall, queue producer не подхватил approved item.

### Эль-косметик (id=82) — полный простой 8д (очередь восстановлена сегодня)

Подробности в Части 2. Причина: uniqualization stall + 9-дневный gap в queue producer.

### Онлайн-школа Anecole (id=84) — полный простой 11д

Подробности в Части 2. Причина: 22 items в in_uniqualization, 0 approved с 2026-04-14.

### ClickPay (id=85) — instagram 59% / tiktok 71%

Главные RC:
- IG: `ig_share_tap_no_progress` (×11), `date_mismatch::ig_picker_wrong_candidate` (×9), `ig_target_not_in_picker` (×7), `ig_camera_open_failed` (×6)
- TT: `tt_upload_confirmation_timeout` (×12, SHIPPED), `tt_account_sheet_closed_before_parse` (×13), `tt_account_menu_unknown_layout` (×10), `switch_failed_unspecified::publish_failed_generic` (×5, NEW bug), `switch_failed_unspecified::tt_account_not_in_list` (×3, ops)

ClickPay — самый затронутый клиент по объёму: топ-3 TT bucket'а плюс IG picker failures. Unic_content = 0 (14-list).

### BigKefBot (id=60) — youtube 90% / tiktok 58%

Главные RC:
- YT: `NULL::NULL` (×7, NEW false-negative), `yt_create_menu_not_reached` (×? часть bucket 10)
- TT: `tt_upload_confirmation_timeout` (×5, SHIPPED), `tt_profile_tab_broken` фрагменты

BigKefBot YT — почти полностью false-negative watchdog (7 из 9 fails в OTA-окне). После fix NULL::NULL YT fail-rate должен нормализоваться.

### Content hunter (id=53) — tiktok 79% / instagram 57% / youtube 54%

Главные RC:
- все платформы: `switch_failed_unspecified::NULL` (×17, единственный клиент — oversized media >70MB)
- TT: `tt_upload_confirmation_timeout` (×5, SHIPPED), `tt_account_menu_unknown_layout` (×2), `tt_post_switch_verify_unrecoverable` (×1), `critical_exception` (×2)
- YT: `yt_create_menu_not_reached` (×3)

Content hunter — единственный пострадавший от adb_push timeout на больших файлах. Chunked-push fix устранит большую часть cross-platform fails.

### Максим Иванов (id=71) — instagram 76% / tiktok 59%

Главные RC:
- IG: `ig_share_tap_no_progress` (×8), `date_mismatch::ig_picker_wrong_candidate` (×2)
- TT: `tt_post_switch_verify_unrecoverable` (×4), `critical_exception` (×4)

### Парфюмерия (id=74) — tiktok 68% / youtube 55%

Главные RC:
- TT: `tt_post_switch_verify_unrecoverable` (×5), `tt_upload_confirmation_timeout` (×4, SHIPPED), `tt_profile_tab_broken` (×1)
- YT: `yt_create_menu_not_reached` (×8), `switch_failed_unspecified::adb_device_not_ready` (×1, ops RF8YA0V7LEH)

Unic_content = 0 (14-list, только 3 items за 30д).

### Forsal (id=65) — tiktok 100%

Главные RC: `tt_upload_confirmation_timeout` (×1, SHIPPED), `tt_post_switch_verify_unrecoverable` (×2), `tt_profile_tab_broken` (×1), `tt_account_menu_unknown_layout` (×2).

OTA-фильтр убрал 6/12 raw fails — реальный window fail-rate до shipped fix ещё выше.

### Ambassadori (id=58) — tiktok 80% / instagram 71%

Главные RC:
- TT: `tt_upload_confirmation_timeout` (×1, SHIPPED), `tt_fg_drift_unrecoverable` (×2)
- IG: `date_mismatch::screencast_pull_failed` (×2), `mediastore_top_mismatch::ig_picker_wrong_candidate` (×1)

OTA убрал 56-78% raw fails — без него метрика была бы некорректной.

### Art Estate (id=49) — tiktok 53%

Главные RC: `tt_upload_confirmation_timeout` (×7, SHIPPED), `tt_account_sheet_closed_before_parse` (×3), `switch_failed_unspecified::publish_failed_generic` (×1, NEW), `anchor_not_found::tt_account_switcher_unreachable` (×1).

### Feminista патчи для глаз (id=100) — tiktok 54%

Главные RC: `tt_upload_confirmation_timeout` (×3, SHIPPED), `tt_account_sheet_closed_before_parse` (×3), `tt_profile_tab_broken` (×3).

### Проекты из 14-list без полного простоя (мониторинг)

- **Александр Ткаченко (id=101):** 20 content за 30д, 0 unic_content — все fails OTA-инцидентом убраны, но stall актуален
- **Септизим (id=83):** 18 content, 0 unic_content — не в high-fail list, legacy content пока держит
- **AXILOR Private (id=96):** 15 content, 0 unic_content — fail-rate <50% в OTA-окне, stall актуален
- **Forchil (id=87):** 13 content, 0 unic_content — не в high-fail list
- **Эзотерика Orakul (id=99):** 13 content, 0 unic_content — не в high-fail list
- **Wanttopay (id=81):** 11 content, 0 unic_content — не в high-fail list
- **Юлия Сваровски (id=102):** 10 content, 0 unic_content — OTA убрал 50%, fail_rate за 7д ~50% по всем платформам
- **Аквабрайт (id=112):** 2 content, 0 unic_content — новый проект, минимум данных

---

## Созданные child-WP (8 штук)

| WP | тип | subject | bucket |
|----|-----|---------|--------|
| #95 | Ошибка | [pipeline][P1] Uniqualization stall: 14 active projects with 0 validator_unic_content (Anecole/Pimble/+12) | systemic — Часть 3 |
| #96 | Ошибка | tt: account-picker bottomsheet silently fails to open (publish_failed_generic, 9 fails 7d) | bucket 12 |
| #97 | Ошибка | yt: post-publish URL polling даёт false-negative (NULL::NULL bucket, 8 false-fails 7d) | bucket 13 |
| #98 | Ошибка | adb_push: chunked-push для медиа >70MB (switch_failed_unspecified::NULL, 17 fails 7d) | bucket 6 |
| #99 | Задача | [ops] re-cable / re-auth device RF8YA0V7LEH (USB unauthorized, 7 fails) | bucket 16 |
| #100 | Задача | [ops] re-login TT my_clickpay на RFGYC31P26P (tt_account_not_in_list ×3) | sub-bucket account_not_in_list |
| #101 | Задача | [ops] re-login TT clickpay_easy на RFGYC2VWBKN + my_clickpay (account_not_in_list ×5) | bucket tt_account_not_in_list |
| #102 | Задача | [investigation] ig_target_not_in_picker — split ops (specific accounts/devices) vs code (UI parser race) (12 fails 7d) | bucket 8 |

## Buckets, не получившие отдельного WP (с обоснованием)

- `ig_share_tap_no_progress` (n=24) — TAIL, покрыто IG share retry tier2 (shipped 2026-05-11). Мониторим до 2026-05-25, при отсутствии падения — открыть регрессионный WP.
- `tt_account_sheet_closed_before_parse` (n=20) — TAIL, родовой с WP #96 (TT bottomsheet timing). Открыть отдельно, если после фикса #96 не уйдёт.
- `tt_post_switch_verify_unrecoverable` (n=17) — TAIL, post-switch verify shipped 2026-05-11. Мониторим, при сохранении — регрессионный WP.
- `tt_profile_tab_broken` (n=17) — TAIL, в общем TT-стабилизация backlog.
- `tt_account_menu_unknown_layout` (n=14) — TAIL, связан с #96 (общий UI-layout). Отдельно при сохранении после фикса.
- `date_mismatch::ig_picker_wrong_candidate` (n=11) — TAIL, sub-issue. WP при росте >15.
- `ig_gallery_no_video_candidate` (n=9) — TAIL, sub-issue family #102.
- `ig_camera_open_failed` (n=8) — TAIL, sub-issue. WP при росте >15.
- `yt_create_menu_not_reached` (n=11) — частично покрыто WP #80 (shipped 2026-05-18). Мониторим.

---

## Out of scope (по spec'у)

- Не делаем code-fix в #79 — это discovery WP.
- Не делаем re-queue — решение пользователя по итогам.
- Не диагностируем VK/FB/Pinterest/Likee.
- OTA-инцидент 2026-05-15 — отдельный root cause, отражён в памяти проекта.
- Shipped fixes (WP #80, WP #82) — мониторинг отдельно.
