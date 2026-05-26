# WP #131 — TT `tt_profile_tab_broken` stale-uiautomator guard: SHIPPED + DEPLOYED 2026-05-26

Спека: `docs/superpowers/specs/2026-05-26-wp131-tt-profile-tab-stale-ui-guard-design.md`
План: `docs/superpowers/plans/2026-05-26-wp131-tt-profile-tab-stale-ui-guard-plan.md`

## Разведка (прод, 23–26.05, после деплоя #130 22.05)

**#131 НЕ поглощена #130.** `tt_profile_tab_broken` по дням: 18.05=7, 19.05=6, 20.05=3, 21.05=3, **22.05=2 (деплой #130)**, 23.05=1 (17 TT/день), 24.05=0 (5 TT/день — обманчиво), **25.05=3 (61 TT/день), 26.05=2**. Держится на baseline ~2-3/день и после #130 → отдельная первопричина.

**`tt_profile_tab_broken` = catch-all из ≥3 причин** (5 свежих post-#130 фейлов, UI-дампы на save.gengo.io):

| task | устройство | экран | первопричина |
|---|---|---|---|
| 9871 | RF8YA0HBR4B | лаунчер, `dumpsys=musically` + `trusted_dumpsys (stale UI)` | **stale uiautomator** |
| 9822 | RF8YA0V5TAH | то же (×5 trusted_dumpsys) | **stale uiautomator** |
| 9616 | RF8YA09S90H | recovery launcher→foregrounded, финал stale | drift+stale (#130 recovery сработал) |
| 9648 | RF8Y80ZV1WF | TikTok + модалка «История просмотров» | блокирующая модалка → **#159** |
| 9652 | RFGYB180RZV | TikTok + «Вы вышли из аккаунта» | разлогин → **#160** |

## Root cause (доминирующий bucket)

Retap-петля `_switch_tiktok` (`account_switcher.py`) на каждой итерации берёт `xml_probe = dump_ui(retries=3)` и гоняет 4 детектора (own/logged_out/reauth/foreign). При залипшем uiautomator `xml_probe` = снимок лаунчера → **все 4 → False** → fall-through в `not_own` retap → 3 попытки исчерпываются → `_fail(tt_2_not_own_profile)` → `tt_profile_tab_broken`. При этом `dumpsys` стабильно показывает TikTok на переднем плане (`switcher_foreground_trusted_dumpsys`), а #130-foreground-guard отрабатывает. По 14 фейлам с 20.05: `fg_recovery` в 13/14, `coords_fallback (no_bounds_in_xml)` в ~11/14. **#130 исправен, маркеры own-profile исправны — гниёт сам uiautomator-дамп.** «Рестарт uiautomator» невозможен (WP #105: нет shell-механизма).

## Фикс

При подтверждённом stale-UI — НЕ жечь retap'ы на протухшем XML, а тапнуть профиль и `break` из петли → управление доходит до **существующей** vision-based проверки аккаунта (`account_switcher.py:2911+`, `_vision_read_current_account` — скриншот при stale корректен), которая постит ТОЛЬКО при `current==target`, иначе уходит в bottomsheet-переключение.

- `_tt_stale_ui_guard_enabled()` — kill-switch env `TT_STALE_UI_OWN_PROFILE_GUARD` (default ON).
- `_tt_probe_looks_stale(xml, target_pkg)` — пустой XML или без пакета TikTok (модалки с пакетом TikTok НЕ stale → идут прежним путём; #159/#160 out-of-scope).
- `_tt_dumpsys_confirms_foreground(target_pkg, reads=3)` — dumpsys ×3 стабильно=TikTok (приём WP #105).
- Guard-блок в retap-петле между `_safe_kb_probe` и `not_own`-логом: при `enabled AND probe_looks_stale AND dumpsys_confirms` → событие `tt_own_profile_stale_ui` + `_save_dump` + `_tt_smart_tap_profile` (coords-fallback) + `break`.

**Wrong-account safety (Codex P1 round 1):** `editor_triggers` доказывают лишь открытие редактора, не аккаунт → отказались от прямого `_tap_plus_and_verify`. `break` отдаёт решение существующей vision-проверке: при `current!=target` → `_open_tt_account_switcher` (переключение), не публикация. **Профиль-тап перед break (Codex P2 round 2):** иначе при реальном Feed vision прочитал бы не-профиль.

## Тесты

`tests/test_account_switcher_tt_stale_ui.py` — 13 тестов: kill-switch ×2, `_tt_probe_looks_stale` ×3, `_tt_dumpsys_confirms_foreground` ×3, интеграция ×5 (stale+vision-match→post; **stale+vision-другой-аккаунт→switcher, НЕ публикация**; dumpsys-нестабилен→guard off; kill-switch off; coords-fallback при smart_tap=False). Полный регресс (5 TT-файлов): **87 passed, 0 fail**. В прод-чекауте после мёрджа: 57 passed (3 файла).

Ревью: spec-compliance (субагент, 9 проверок) ✅ + code-quality (субагент) **Approve** (2 minor закрыты) + codex review спека/плана/диффа — всё clean.

## Деплой

- Worktree `wp131-tt-stale-ui-guard` (5 коммитов `2fa8d96..ae8d8c9`) → `git merge --no-ff` в прод `/root/.openclaw/workspace-genri/autowarm` main `f569f5d`. `account_switcher.py` на main не менялся с базы → без конфликтов.
- `git push origin main` `1af91ce..f569f5d` (GenGo2/delivery-contenthunter). Python спавнится per-task → **PM2 restart НЕ нужен**.
- Worktree удалён, ветка merged+deleted.

## Остаток (24h verify, ~27.05)

Query `SELECT count(*) FROM publish_tasks p, jsonb_array_elements(p.events) e WHERE e->'meta'->>'category'='tt_own_profile_stale_ui' AND p.updated_at >= '2026-05-26'` + динамика `error_code='tt_profile_tab_broken'` (цель — к нулю в stale-bucket). Кросс-сверка task'ов с событием против финального статуса (done/published = безопасно). При подтверждении WP #131 → «Готово». Откат: `TT_STALE_UI_OWN_PROFILE_GUARD=0`.

Out-of-scope child-WP: **#159** («История просмотров» dismiss, паттерн WP #106), **#160** (разлогин detect → account_blocks, паттерн WP #93).
