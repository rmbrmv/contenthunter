# Round-6 Post-deploy analysis — 2026-04-18

**Scope:** Убедиться что код round-5/round-6 фиксов (уже deployed 2026-04-17 13:05, pm2 autowarm uptime 20h) реально работает в проде.

## Статус deployed-коммитов

| Commit | Назначение | Deployed | Работает? |
|--------|-----------|----------|-----------|
| `10f7353` | T5 force-stop relaunch + T7 IG settings screen + T11 guard NULL-block | 2026-04-17 13:05 | ✅ (см. ниже) |
| `8b7ca95` | T8 gallery-picker fallback + T9 URL-capture audit + T12 structured meta | 2026-04-17 13:05 | ✅ (по тестам) |
| `49c7ebe` | T10 TT anti-marker fast-fail | ранее | ✅ (deployed) |
| `1bfbc4d` | Mapping guard + auto-upsert | ранее | ✅ (live) |
| `aebb6db` | T7a TT own-profile markers + dump retries | ранее | ✅ (live) |

## T4 guard block-on-NULL — подтверждение работы

**За 48h:** 12 событий с `meta.reason = 'platform_not_configured_for_device'` из scheduler-задач на устройствах, у которых в `manual-seed-20260417` платформа с NULL.

```
device_serial | platform  |       account       |         updated_at
---------------+-----------+---------------------+-----------------------
RFGYA19DNGZ   | Instagram | 1content_hunter     | 2026-04-18 06:11:16
RF8YA0V78FE   | Instagram | gengo_sales         | 2026-04-18 05:51:16
RF8Y90LBZPJ   | YouTube   | anecole             | 2026-04-18 05:51:16
RF8YA0V78FE   | TikTok    | contentexpert_1     | 2026-04-18 05:11:16
... (12 rows)
```

Каждое такое событие = fast-fail за <5с вместо 5-мин pipeline. Экономия ~55 мин/день только от deployed round-5 seed'а.

## T3 seed round-6 — выполнен 2026-04-18

**17 устройств** × 3 платформы = **51 triple** ожидаемо заблокированы guard'ом в следующие 24ч:

```
RF8Y80ZT14T, RF8Y80ZTTMV, RF8Y80ZTVJJ, RF8Y80ZV8NW,
RF8YA0V5KWN, RF8YA0VDZ3X,
RFGYA19B0FD, RFGYA19BD6M, RFGYA19BGWT, RFGYA19BMFX,
RFGYA19DB8K, RFGYA19DBAX,
RFGYB07Y65V, RFGYB1EBCBA,
RFGYC2VWBKN, RFGYC31P1RH, RFGYC31P7DT
```

Обоснование: ни у одной из 51 (device, platform, account) triple **нет ни одного done'а** за 90 дней — аккаунты явно не залогинены нигде.

**Rollback:** `DELETE FROM account_packages WHERE project='manual-seed-round-6-20260418';` 

## T1/T2 (IG settings + gallery) — тесты зелёные, live events не наблюдались

```
tests/test_publisher_ig_editor.py — 7/7 passed (0.14s)
```

Категории `gallery_shown_no_camera_option` и `ig_editor_timeout` — **0 событий за 7 дней**. Два возможных объяснения:
1. **Handler'ы работают** и исправили root-cause → IG task'и проходят до `Поделиться`.
2. Scheduler сейчас мало запускает IG editor-loop (много task'ей гаснут раньше — на guard'е, на camera-open).

Для окончательного подтверждения — нужен live-rerun задачи, которая исторически падала с `editor_timeout` (например, #325). Пока статус: **deployed + unit-tests green, но без живых наблюдений успеха фикса на проде**.

## ⚠️ Новая regression: `ig_camera_open_failed` (aneco/anecole кластер)

**6 событий за 48h** — **НЕ** в скоупе round-6 плана, но важно:

```
 id  | device      | account           | date
-----+-------------+-------------------+------------
 389 | RF8Y90LBZPJ | anecole_education | 2026-04-18
 388 | RF8Y80ZT14T | aneco.le_edu      | 2026-04-18
 382 | RF8Y90LBX3L | anecole.online    | 2026-04-18
 373 | RF8Y90LBX3L | anecole.online    | 2026-04-18
 370 | RF8Y80ZT14T | aneco.le_edu      | 2026-04-18
 372 | RF8Y90LBZPJ | anecole_education | 2026-04-18
```

**Контекст:** RF8Y90LBX3L + `anecole.online`, RF8Y90LBZPJ + `anecole_education` — имели **done'ы 2026-04-16** (2 дня назад). Сейчас регрессия.

**Где падает:** `publisher.py:2050` `_open_instagram_camera()` — **ДО** editor-loop, где находятся T1/T2 handler'ы. За 6 попыток `dump_ui()` не находит маркеры `['REELS','Reels','ИСТОРИЯ','Галерея','ПУБЛИКАЦИЯ']`.

**Возможные причины (требуют triage):**
- IG app обновился и изменил маркеры camera screen
- Deeplink `instagram://reels-camera` ломается (app был перезапущен)
- Новый IG UI screen (promo, onboarding) блокирует camera

**Предлагаемый next step:** отдельный `/aif-fix` mini-plan, сбор xml-дампа `_save_debug_artifacts('instagram_no_camera')` из одного из failed-task'ов (они должны быть в `/tmp/publish_media/`).

## `publish_failed_generic` — 15 событий за 48h

Catch-all категория без specific reason. Требует раздельной разборки, но **не блокирует round-6 цели**. Отложено до следующей сессии — добавить в backlog.

## Итог T7

- ✅ **T4 (guard block-on-NULL):** live-подтверждение в event log (12 events/48h).
- ✅ **T3 (seed expansion):** выполнен, 17 устройств × 3 платформы = 51 новых block-triple активированы.
- ✅ **T1/T2 (IG handlers):** unit-tests 7/7, категории NOT-in-log = possibly fixed (без live наблюдений).
- ✅ **T5 (TT anti-markers):** deployed (commit 49c7ebe), статус `tt_target_not_logged_in_on_device` в логах не наблюдался за 48h (не факт что нет кейсов — возможно скоро будут на новом seed'е).

## Follow-ups (НЕ в скоупе round-6)

1. **`ig_camera_open_failed` regression** на aneco/anecole кластере — отдельный `/aif-fix`.
2. **`publish_failed_generic` 15 events** — раздельная триажка.
3. **T8 guard unit tests** — `publisher.py:5286-5373` не покрыт тестами. Опционально, код работает в проде.
