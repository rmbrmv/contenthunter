# `publish_failed_generic` catch-all — 7d triage

**Сборка:** 2026-04-20 ~05:45 UTC.
**Контекст:** closing memory `project_publish_followups.md` §2 (15 events/48h требуют triage).
**Источник:** план-потомок `contenthunter/.ai-factory/plans/open-followups-20260420.md` T4.

## TL;DR

**Не нужен отдельный plan-потомок по catch-all.** T1 category-propagation (tt-publishing-resolution merge `ff3ec8b` 2026-04-19 20:04 UTC) **работает**: за post-deploy окно — **0 новых** `publish_failed_generic` событий. Все 11 historical events — pre-deploy.

**Реальный follow-up найден в T2 evidence:** generalize IG T4 guard-terminal-status (`status=skipped_config_missing`) на TT/YT. 18 TT guard-hits в 48h до сих пор получают `status=failed`, что загрязняет failed-метрику и вводит в заблуждение acceptance-критерии.

## Данные: всё `publish_failed_generic` за 7 дней

| id | platform | account | status | started_at (UTC) | other categories | pre/post deploy |
|---:|---|---|---|---|---|---|
| 388 | IG | aneco.le_edu | skipped_config_missing | 2026-04-19 17:43 | ig_camera_open_failed, manual_retry_after_deploy, skipped_config_missing | Pre-deploy event, post-deploy terminal |
| 370 | IG | aneco.le_edu | skipped_config_missing | 2026-04-19 17:34 | ig_camera_open_failed, manual_retry_after_deploy, skipped_config_missing | Pre-deploy event, post-deploy terminal |
| 415 | TT | procontent_lab  | failed | 2026-04-18 11:25 | — | Pre-deploy |
| 414 | TT | lead_content_   | failed | 2026-04-18 11:25 | — | Pre-deploy |
| 413 | TT | expertcontentlab| failed | 2026-04-18 11:24 | — | Pre-deploy |
| 411 | TT | content_expert_1| failed | 2026-04-18 11:24 | — | Pre-deploy |
| 393 | TT | aneco_le        | failed | 2026-04-18 05:51 | — | Pre-deploy |
| 387 | TT | lead_content_   | failed | 2026-04-18 05:12 | — | Pre-deploy |
| 379 | TT | aneco_le        | failed | 2026-04-18 05:11 | — | Pre-deploy |
| 385 | TT | expertcontentlab| failed | 2026-04-18 05:11 | — | Pre-deploy |
| 383 | TT | content_expert_1| failed | 2026-04-18 05:11 | — | Pre-deploy |

## Классификация

### Bucket 1 — TT pre-deploy (9 events, все 2026-04-18)

Все **ДО** tt-publishing-resolution T1 merge `ff3ec8b` (2026-04-19 20:04 UTC). Без additional categories в events. Это диагностический baseline для T1 — именно их наличие спровоцировало план tt-publishing-resolution. **Action: none** — T1 закрыл этот класс. В post-deploy окне (2026-04-19 20:04 UTC+) **0 новых TT `publish_failed_generic`**.

### Bucket 2 — IG manual retry (2 events, task 370 и 388)

Оба на aneco.le_edu / RF8Y80ZT14T. Последовательность:
1. (Pre-deploy) Первая попытка: `ig_camera_open_failed` → error-event → `publish_failed_generic` → статус становится `failed` (или in-retry).
2. Задача вручную переподнята с меткой `manual_retry_after_deploy`.
3. Post-deploy: guard на aneco.le_edu (NULL tiktok/instagram mapping?) — **не срабатывает** на IG platform (guard-хит другой природы — device seeded без mapping).
4. Финальный status: `skipped_config_missing` (guard правильно терминальный статус).
5. Но исторические events `publish_failed_generic` от шага 1 остаются в записи.

**Action: none** — эти 2 события — артефакт manual retry вокруг deploy. На реальном метрике post-deploy они не попадают в actively-failing подмножество.

### Bucket 3 — true catch-all в post-deploy window

**0 events.** T1 category-propagation делает свою работу.

## Real follow-up (найден сбоку)

**TT/YT guard-terminal-status consistency** — не связано напрямую с catch-all, но видимо в T2 evidence:

```
TT 48h status breakdown:
  failed                 | guard-block |    18   ← должен быть skipped_config_missing
  failed                 | real-fail   |     6
  skipped_config_missing | guard-block |     9
```

18 TT задач попадают в `failed` с guard-message в `log`/`events`, 9 — корректно в `skipped_config_missing`. **Разделение должно быть deterministic** — либо все guard-hits → `skipped_config_missing`, либо никто. Для IG T4 из `ig-publishing-resolution.md` — полностью на `skipped_config_missing`, логика правильная. Для TT/YT — leak.

**Root cause гипотеза:** `publisher.py::_check_account_device_mapping` (landmark `:5286-5373` из `project_publish_guard_schema`) вызывается на IG path до `publish_instagram_reel`, но для TT — позже / в другом месте, и промежуточный `publish_tt` может бросать error → `status=failed` до того, как guard успеет terminal.

## Action items

1. **Memory `project_publish_followups.md` §2** — пометить как closed: catch-all в post-deploy окне = 0. Обновить запись: "T1 category-propagation (commit ff3ec8b 2026-04-19) устранил класс, historical events остаются как baseline".
2. **Новый follow-up:** вместо catch-all plan предлагается конкретный fix-plan —
   ```
   /aif-plan full "Generalize guard-terminal-status (IG T4 pattern) на TT и YT publishing paths"
   ```
   С acceptance: 0 случаев `status=failed` с guard-маркером в 48h post-deploy окне; все guard-hits → `skipped_config_missing`.
3. **НЕ заводить** fix-plan по catch-all отдельно — это дублировало бы scope уже закрытого T1.
4. **Guard unit-тесты (T6 umbrella)** — при имплементации обязательно покрыть и TT, и YT пути, чтобы регрессия guard-status не уехала.

## Метаданные

- DB: `openclaw@localhost/openclaw`.
- Связанные artifacts: `tt-publishing-48h-20260420.md` (B раздел — обнаружение TT leak), `farming-baseline-20260419.md` (pre-deploy TT baseline), autowarm `ig-publishing-resolution.md` (IG T4 reference).
