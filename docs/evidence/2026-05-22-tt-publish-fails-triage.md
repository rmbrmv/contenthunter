# TikTok publish-fails triage — 2026-05-22

**Скоуп:** только TikTok, упавшие задачи за сегодня (`platform='TikTok' AND status='failed' AND created_at::date='2026-05-22' AND testbench=false`). Сетевой `switch_failed_unspecified` / `adb_devices_unreachable` исключён по указанию (уже починен).

**Метод:** группировка по последнему `events[].meta.category` (не по `error_code` — он пишет первую/preflight ошибку, не итоговую). Скринкасты + UI-dump-labels (`probe_top_labels`) для подтверждения.

## Итог: 13 упавших задач

### По эмитнутому коду (как видно в логах/дашбордах)

| Категория | Кол-во | Задачи |
|---|:--:|---|
| tt_account_sheet_closed_before_parse | 4 | 9116, 9179, 9183, 9239 |
| tt_post_switch_verify_unrecoverable | 2 | 9124, 9190 |
| tt_profile_tab_broken | 2 | 9117, 9156 |
| tt_upload_confirmation_timeout | 2 | 9171, 9175 |
| tt_fg_drift_unrecoverable | 1 | 9210 |
| tt_account_not_in_list | 1 | 9208 |
| screencast_stop_failed (ec=tt_fg_drift_unrecoverable) | 1 | 9229 |

### По РЕАЛЬНОЙ первопричине (после разбора скринкастов)

Бакет `tt_account_sheet_closed_before_parse` оказался **смешанным**: половина — это foreground-drift, который guard не распознал (probe панели аккаунтов запустился на чужом экране ДО детекта ухода TikTok).

| Первопричина | Кол-во | Задачи | Существующий WP |
|---|:--:|---|---|
| **TikTok теряет передний план на switch** (→Instagram / рестарт-петля / launcher) | **4** | 9116, 9210, 9229, 9239 | частично #121 (только launcher, кейс 9239), #119 (IG-аналог) — **TT-специфичного нет → WP #130** |
| bottomsheet не открывается (новый layout «\|\|\|▾») | 2 | 9179, 9183 | #96 |
| tt_post_switch_verify_unrecoverable | 2 | 9124, 9190 | #67 |
| tt_profile_tab_broken (`tt_2_not_own_profile`) | 2 | 9117, 9156 | — |
| tt_upload_confirmation_timeout | 2 | 9171, 9175 | #118 / #122 |
| tt_account_not_in_list | 1 | 9208 | #100 / #101 |

## Разбор foreground-drift кластера (топ-1, 4/13 = 31%)

- **9116** (`sale.for19`) — финал на **Instagram** (профиль `jasleen`, табы Сетка/Reels/Фото-с-вами, кнопка «Подписаться»). TikTok не на переднем плане. Эмитнулся как `tt_account_sheet_closed_before_parse` (мис-классификация). `probe_top_labels` подтверждает Instagram-контент.
- **9239** (`axilor_woman`) — `probe_top_labels` в момент фейла = **домашний лаунчер Android** («Страница 1 из 2», «Астана», «Google Play», «Камера»). Финальный кадр (после cleanup) — TikTok-профиль axilor. Эмитнулся как `tt_account_sheet_closed_before_parse`. **Пересекается с #121.**
- **9210** (`dubai_asset_expert`) — финал = **сплэш TikTok** (чёрный экран с лого); по логам ~10× `switcher_foreground_pkg_disagree` + `recents_close_all_recovery`, не восстановился → `tt_fg_drift_unrecoverable`. Петля перезапуска.
- **9229** (`thespbpropertyguide`) — `tt_fg_drift_unrecoverable`, запись не сохранилась (`screencast_stop_failed`).

### Контраст: «настоящий» bottomsheet-not-open (9179, 9183 → #96)
- **9179** (`tkachenko_pro5`) — финал = TikTok-профиль ТЕКУЩЕГО аккаунта `tkachenko_health26` (не target). Виден дропдаун-триггер «**|||▾**» рядом с username. Тап по тексту username = no-op; нужен тап по каретке дропдауна. `storyringhas_consumed_story_true` всё ещё в дампе, но Stories-pivot не сработал (т.к. после фикса WP #112 тап уходит на username, а не на аватарку). → Phase-2 «Меню профиля» не триггерится.
- **9183** (`swarovski_energy`) — то же (текущий `swarovski_life`, не target).

**Важно:** фикс WP #112 (story-ring tap, PR #85) держится — это НЕ рецидив storyring-бага. Сегодняшний рост `tt_account_sheet_closed_before_parse` обусловлен (а) мис-классифицированным foreground-drift и (б) тем, что после устранения story-ring тапа панель всё равно не открывается тапом по username (территория #96).

## Решение

**WP #130 — SHIPPED+DEPLOYED 2026-05-22** (delivery-contenthunter PR #97, прод-коммит `486fec2`; статус «Тестирование»). Foreground-guard на шаге `tt_3_open_list` (зеркало IG WP #119): перед открытием панели аккаунтов проверяем `foreground == com.zhiliaoapp.musically`; если нет → relaunch + re-navigate + verify own-profile, иначе честный `tt_fg_drift_unrecoverable` вместо `tt_account_sheet_closed_before_parse`. Placement A (перед `_open_tt_account_switcher`) + placement B (re-check при drift во время probe). Kill-switch `TT_SWITCH_FG_GUARD_ENABLED` (default ON). 10 тестов, 217 switcher-тестов зелёные, codex 2 раунда P2 чисто. pm2 restart не нужен (publisher per-task spawn). Verify утром 23.05.

**WP #131 — заведена в бэклог** (`tt_profile_tab_broken`, 9117/9156): после перехода в профиль-таб бот не распознаёт собственный профиль (`tt_2_not_own_profile`) — отдельный баг навигации, требует разбора UI-dump.

**Остаток (вне scope #130):** усиление recovery для петли перезапуска TikTok (9210/9229) — она уже корректно классифицируется как `tt_fg_drift_unrecoverable`, но восстановление не справляется.

## SQL для воспроизведения

```sql
WITH tt AS (
  SELECT id, error_code,
    (SELECT e->'meta'->>'category' FROM jsonb_array_elements(events) e
       WHERE e->>'type'='error' AND e->'meta'->>'category' IS NOT NULL
         AND e->'meta'->>'category' <> 'adb_devices_unreachable'
       ORDER BY (e->>'ts') DESC LIMIT 1) AS real_category
  FROM publish_tasks
  WHERE platform='TikTok' AND status='failed'
    AND created_at::date='2026-05-22' AND testbench=false)
SELECT COALESCE(real_category,'(none)'), count(*) FROM tt GROUP BY 1 ORDER BY 2 DESC;
```
