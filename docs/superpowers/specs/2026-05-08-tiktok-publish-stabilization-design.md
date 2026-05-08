# TikTok publish stabilization — design

**Дата:** 2026-05-08
**Статус:** draft (pending codex review + user approval)
**Worktree:** `tt-publish-design-20260508`

## Контекст

`publisher_tiktok.py` (961 строка, `TikTokMixin`) уже интегрирован в общий
`DevicePublisher` пайплайн вместе с IG/YT и публикует через тот же entry-point
(`publisher_base.py:3958 self.publish_tiktok(remote_path)`). Тем не менее:

- Last 14 дней TT: **1 done / 365** (0.27%) против YT 225/359 (63%) и IG 106/693 (15%).
- Последняя реальная успешная TT-публикация — task 262 от 2026-04-14
  (24 дня тишины).
- Падает на всех 8 raspberry-устройствах, не только #171 (известная проблема
  из памяти `project_revision_phone171_backlog.md`).

## Симптом и категории фейлов

Источник правды — `events[].meta.category`, не колонка `error_code`
(она пишет первую ошибку — обычно preflight, см. memory
`feedback_publisher_error_code_misleading.md`).

Распределение по category за последние 7 дней (TT failed only):

| Category | Tasks | Доля |
|----------|------:|-----:|
| `tt_target_not_on_device` | 146 | ~63% от switcher-fail |
| `tt_profile_tab_broken` | 54 | ~23% |
| `watchdog_fired` | 28 | downstream |
| `tt_fg_drift_escalated` | 20 | downstream |
| `tt_upload_confirmation_timeout` | 14 | post-share, не switcher |
| `tt_account_sheet_closed_before_parse` | 5 | switcher |

Минимум 73% всех TT-фейлов — switcher не доводит до tap-share-button.

## Ключевые находки разведки

### Concrete failure trace (task 3773, raspberry=7, target=`clickpay_app`)
1. `_ensure_foreground('TikTok')` ✓
2. `_go_to_profile_tab` тапает координаты (~972,2320) — bottom-nav «Я»
3. `_tt_is_own_profile(xml)` → False (видит `text="Подписаться"` + `text="Сообщение"`)
4. Dump показывает handle = `@qazaqsha_sozder.arnasy1` (4.3M followers, казахский TikToker — типичный Suggestion-feed профиль)
5. retap1 → всё ещё foreign
6. После 2 foreign → `_tt_try_bottomsheet_recovery`:
   - tap на header → ждёт anchor
     (`Управление аккаунтами`/`Manage accounts`/`Switch account`)
   - **anchor не найден** → `bottomsheet_not_open`
7. `_fail('tt_2_target_not_logged_in')` с `error_code='tt_target_not_on_device'`

### Live phone #19 диагностика
- TT version **44.4.3** (свежий)
- Splash activity висит в `topResumedActivity` даже когда feed уже виден
  → `_ensure_foreground` через `dumpsys activity` ненадёжен
- `uiautomator dump` возвращает «could not get idle state» —
  TT 44.4.3 имеет постоянные animations в feed, idle-state не достигается
- Tap по координатам (970, 2280) и (1020, 2305) **не попадает** на «Профиль»
  — feed просто скроллится вертикально

### Codex critique (key push-backs)
- Не утверждать «TT semantics changed». Live evidence лучше объясняется
  **coord drift** (наш tap mаимо bottom-nav иконки) +
  TT feed уже сидит на foreign profile из persistent state.
- `tt_target_not_on_device` — **contaminated category**: может быть real absence
  ИЛИ false-classification после failed nav. Audit-first без разделения категорий
  скрыл бы регрессию вместо фикса.
- «Bottomsheet account-switcher only on own-profile» — структурно верно для
  текущего кода, но не доказано для самого TT (foreign profile может иметь
  свои tap-affordances).
- Settings activity intent для TT хуже, чем для YT (obfuscation, non-exported
  activities, Permission Denial). Только enumerate+validate, не assume.

## Архитектурное решение — четырёхфазная стабилизация

Каждая фаза — отдельная итерация: спека → план → impl → testbench smoke
→ корректировка → следующая фаза. Гейт перехода — табличные критерии,
а не «по ощущению».

Изначальный набросок имел отдельную «pure observability» итерацию.
По Codex-критике это убрано: при success rate 1/365 outage-level pure
observability — пассивно. Объединяем classification + nav fix в одну
итерацию (Phase 1) за feature flag, эмитим новые категории сразу, чтобы
fix мерился прямо на канарной выборке.

### Фаза 1 — Classification + bound-based nav (combined)

**Цель:** перестать смешивать «не дошли до switcher» и «дошли, target
отсутствует», и одновременно починить навигацию.

#### 1a — Observability / classification

`account_switcher.py:_switch_tiktok` + `_tt_try_bottomsheet_recovery`:

- Заменить унифицированный `tt_target_not_on_device` на 3 категории:
  - `tt_profile_nav_failed_foreign` — 3 retap не вывели на own profile,
    остались на foreign (старое поведение, но переименованное).
  - `tt_account_switcher_unreachable` — header-tap не открыл bottomsheet
    (anchor not found / FLAG_SECURE / sheet не виден).
  - `tt_account_switcher_target_absent` — bottomsheet открыт И его контент
    распарсен (≥1 строка аккаунта прочитана) И scroll исчерпан, но
    `target` не найден. Без этих трёх условий выдавать
    `tt_account_switcher_unreachable` — не путать «не открылось» и
    «открылось, но target там нет».
- В event meta каждого transition записывать: `tap_coords`,
  `tap_target_label`, `tap_method` (`xml_bounds|vision|coords_fallback`),
  `xml_usable`, `screencap_url`, `transition_outcome`
  (`own_profile|foreign|feed|unknown`), `account_rows_seen` (для
  bottomsheet'а), `scroll_attempts`.
- Скриншоты до/после tap (`pre_tap`/`post_tap`) — PNG через
  `screen_recorder.py`. Cap 10 на task. TTL 14 дней (как
  `autowarm_ui_dumps`).
- `error_code` mapping: новые категории как новые коды, старый
  `tt_target_not_on_device` оставить как **alias** в
  `_PUBLISH_ERROR_CODES_REGISTRY` — frontend-фильтры/analytics/alerts
  не ломаются. Документировать deprecation.

#### 1b — Bound-based nav

`account_switcher.py:_go_to_profile_tab` для TikTok:

1. Если `dump_ui` usable (`is_dump_usable` ≥5 labeled elements):
   парсить XML, найти clickable element с `text` или `content-desc` ∈
   `{Профиль, Profile, Me, Я, You}` И `bounds[1] >= screen_height * 0.85`
   (нижняя 15%) → tap по center bounds.
2. Если XML не usable: `screencap` + Claude vision call с
   инструкцией «найди иконку bottom-nav «Профиль/Profile», верни x,y».
   Reuse `publisher_vision_recovery.attempt_vision_recovery`.
3. Координаты cfg (972, 2320) — последний fallback. Логировать
   `tap_method=coords_fallback` отдельно — это сигнал drift.

`_tt_is_own_profile` усилить positive evidence (Codex-pushback):

- Сейчас «не foreign» эквивалентно «own» — бритвенно. Требовать
  positive marker из `_TT_OWN_PROFILE_MARKERS` И отсутствие foreign
  markers одновременно. Если usable XML без обоих — `unknown`,
  не `own`. Vision-fallback для `unknown`.

Обновить `_TT_OWN_PROFILE_MARKERS`/`_TT_FOREIGN_PROFILE_MARKERS` по
реальным dump'ам phone #19 (TT 44.4.3).

`publisher_tiktok.py:publish_tiktok` — использовать обновлённый nav
при tap-share (тот же gap проявится при выходе на share-screen).

**Feature flag:** `tt_bound_nav_enabled` в `factory_settings` или env.
Старый код-path остаётся при flag=false.

**Smoke на phone #19** (raspberry=7, RF8YA0W57EP, S21 1080×2340):
- 2 TT-аккаунта logged-in: `gennadiya4` (pack 19b),
  `user70415121188138` (pack 19a).
- 10 testbench publish_tasks: 5 на каждый аккаунт, разные caption +
  2-3 hashtags + 1-2 проверки с очень коротким caption + 1 без
  hashtags. Geotag не выставляется (consistent с IG/YT).
- Verify: post-publish URL captured, `_tt_is_own_profile` ✓
  (positive markers found), `is_published_tiktok=true` в DB.

**Phase 1 gate (move to Phase 2):**
- Phone #19: success rate ≥80% (8/10 publish_tasks done с реальным
  post_url). При <80% — возврат к доске + анализ events. Smoke gate,
  не proof; 10 attempts недостаточно для генерализации, но достаточно
  для канарного допуска.

**Риски:**
- Instrumentation влияет на UI timing — больше dump_ui/screencap
  → больше шансов race с TT animations. Mitigation: измерить latency
  до/после, при росте >20% — sample-based sampling (не каждый transition).
- Vision-fallback cost/latency не ограничен. Mitigation: cap
  vision-calls 2 на switch попытку; budget tracking в task meta.
- Privacy: скриншоты TT могут содержать DM/notifications/personal data.
  Mitigation: стандартный gengo S3 ACL (private bucket), TTL 14 дней,
  не публиковать ссылки за пределами internal evidence-репо. Будущий
  followup: redact handle поверх top-bar если фича появится в законах
  региона.
- False-positive own-profile (markers conflict). Mitigation: positive+
  negative evidence required (см. выше).
- Locale/device density: A17/older Samsung S models, скейлинг шрифта,
  gesture-nav. Mitigation: smoke начинаем на S21 1080×2340 (большая
  доля fleet), затем расширяем.

### Фаза 2 — Canary валидация (производственный sample)

**Цель:** проверить что Phase-1 fix работает не только на phone #19.

После Phase-1 deploy:
- Re-queue минимум **30 publish_tasks** через iter-1 split-категории,
  распределённых по ≥4 raspberry-устройствам и ≥2 классам экрана
  (1080×2340 + что-то другое).
- Idempotency guard перед re-queue (см. ниже): не re-queue task'и где
  `post_url IS NOT NULL` (даже если status=failed) — это защищает от
  duplicate post.
- Наблюдение 24-48 ч.

**Phase 2 decision table:**

| Доминирующая category | Что делать |
|---|---|
| `tt_profile_nav_failed_foreign` ≥30% от 30 attempts | bound-based nav недостаточен → Phase 4 backlog (Settings/longpress investigation). Не блокировать rollout, но открыть отдельный design. |
| `tt_account_switcher_unreachable` ≥30% | Bottomsheet логика сломана независимо. Iteration на header-tap логику. Не идём в Phase 3. |
| `tt_account_switcher_target_absent` ≥30% **с подтверждённым evidence** (bottomsheet opened + ≥1 row parsed + scroll exhausted) | Phase 3 audit нужен. |
| Success rate ≥30% over 30 attempts И ни одна failure-category не доминирует | Phase 1 fix работает → Phase 4 (rollout). |
| Success rate <15% | Откат feature flag, root-cause analysis, новая итерация. |

### Фаза 3 — Account audit (только при evidence)

Активируется только если Phase 2 decision table указала
`target_absent` ≥30% **с evidence**. Иначе пропускается.

- Запустить `account_revision.py --device-number ...` по raspberry,
  где наблюдался target_absent.
- Сверить `factory_inst_accounts.username + active=true` с реальным
  TT state. Для подтверждённого absence — пометить `tt_block` JSONB
  на `factory_reg_accounts`.
- Re-queue только те publish_tasks, где target подтверждён.

**Phase 3 outcome:** ≥80% подтверждённых target_absent кейсов помечены
в DB; recovered (если бы re-queued после re-login) tasks помечены для
manual operator action.

### Фаза 4 — Production rollout

- Перевести feature flag `tt_bound_nav_enabled=true` глобально.
- Bulk re-queue failed TT-tasks за последние 14 дней через
  `publish_queue` (memory `reference_publish_requeue_path.md`):
  - **idempotency guard:** только task'и с `post_url IS NULL` И
    статус ∈ {failed, error}. Подтверждение в DB query.
  - Throttle: 50 в час на raspberry, чтобы не перегрузить устройства.
- Метрики на existing analytics dashboard:
  - TT success rate per-raspberry, per-day.
  - Распределение event-категорий.
  - `tap_method` распределение (xml_bounds vs vision vs coords_fallback).

**Phase 4 success metric:** TT success rate ≥30% за 7-дневное окно
после rollout, измеренное по publish_tasks.status='done' / total
(`platform='TikTok' AND created_at > NOW() - INTERVAL '7 days'`).
Цель — половина YT-уровня, реалистично с учётом TT-app instability
(continuous animations, splash-activity lies).

**Backlog (не входит в эту spec'у):**
- `Vision-recovery` extension для broader state classification
  (не только fg-drift) — другие этапы TT-публикации.
- Settings activity / longpress / avatar enumeration —
  только если Phase 2 показывает `tt_profile_nav_failed_foreign`
  ≥30% после bound-based nav. Отдельный design.
- `tt_upload_confirmation_timeout` (14 за 7д) — отдельная проблема,
  не switcher.
- `account_revision` reuse того же bound-based nav code (DRY).
- Account state buckets: suspended/captcha/age-gate/upload-limit —
  отдельные категории.

## Что **не** делаем (явные YAGNI)

- **Не** перепиываем `publish_tiktok` с нуля. 961 строка работает в `done=1`
  case (последний 2026-04-14) — значит editor / share / URL-capture части
  здоровы. Корневая проблема в switcher.
- **Не** добавляем явный выбор геометки (`select_location`) сейчас —
  user upфлагнул это как not-priority, и одинаковый gap есть в IG/YT.
  Может быть отдельный design позже.
- **Не** меняем DB schema (`is_published_tiktok` уже есть, error_code
  vocabulary расширяется alias-режимом).

## Definition of Done

- TT-publish успешно завершается end-to-end на phone #19 для обоих
  logged-in аккаунтов (`gennadiya4`, `user70415121188138`) с реальной
  публикацией видео + caption + hashtags.
- post-publish URL captured и записан в `publish_tasks.post_url`.
- `is_published_tiktok=true` на `factory_inst_accounts` после публикации.
- Frontend `📣 опубликовано` бейдж работает для TT.
- Phase 1 smoke gate (≥80% / 10 phone-#19 attempts) пройден.
- Phase 2 canary gate (≥30% / 30 attempts / ≥4 raspberry / ≥2 screen
  classes) пройден.
- Phase 4 production gate (≥30% over 7-day window) измерен и достигнут.
- Все evidence-артефакты в
  `docs/evidence/2026-05-08-tt-publish-stabilization-*.md`.
- Codex review пройден на spec и на каждый implementation plan.

## Зависимости

- Память (читать перед каждой итерацией):
  `project_revision_phone171_backlog.md`,
  `feedback_publisher_error_code_misleading.md`,
  `project_publisher_obstacle_kb.md`,
  `feedback_codex_review_specs.md`,
  `reference_publisher_proxy_api.md`,
  `feedback_ui_automation_edge_cases.md`.
- Тесты: `test_account_switcher_tt.py` (3 кейса), `test_publish_handle_assertion.py`.
- Deploy path: PM2 ecosystem (`feedback_deploy_scope_constraints.md`),
  auto-push hook в `/root/.openclaw/workspace-genri/autowarm/`.

## Open questions для следующей итерации

1. Phase-1 smoke gate (≥80% phone-#19) подтверждает coord drift, но не
   доказывает что fix работает на других screen-sizes. Phase-2 canary
   обязан покрыть ≥2 screen classes для генерализации.
2. `tt_upload_confirmation_timeout` (14 за 7 дней) — отдельная проблема,
   не покрывается этой spec'ой. Backlog.
3. Vision-recovery API сейчас single-shot — нужно ли расширять до
   многоступенчатого (как в IG ai_unstuck loop) для TT? Открыто после
   Phase-2 evidence.
4. Account state buckets (suspended/captcha/age-gate/upload-limit) —
   нужны как отдельные категории, чтобы не полагаться на
   `tt_account_switcher_target_absent` для inventory hygiene. Backlog.
