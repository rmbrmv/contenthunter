# WP #132 подсигнатура A — снятие промо YouTube Premium — SHIPPED+DEPLOYED 2026-05-22

**WP**: [OpenProject #132](https://openproject.contenthunter.ru/work_packages/132) → статус **Тестирование**
**Spec**: `docs/superpowers/specs/2026-05-22-yt-premium-promo-dismiss-design.md`
**Plan**: `docs/superpowers/plans/2026-05-22-yt-premium-promo-dismiss-plan.md`
**Triage evidence**: `docs/evidence/2026-05-22-yt-publish-fails-triage.md`

## Что выложено

Прод-репо `GenGo2/delivery-contenthunter` (autowarm), main:
- `7713cca` — `account_switcher.py`: детектор `_yt_is_premium_promo`, kill-switch `_premium_dismiss_enabled`, helper `_exact_match_triggers` (рефактор WP #88), recovery `_yt_dismiss_premium_promo_and_retap`, врезка в `_tap_plus_and_verify`, новый error_code `yt_create_menu_premium_blocking`.
- `a407343` — тесты + 3 фикстуры (23 теста).

GitHub main подтверждён = `a407343` (ls-remote). 23 теста проходят в прод-контексте; полный switcher-прогон 41 passed + 1 пред-существующий fail (`test_strict_verify_falls_back_safely_on_malformed_xml` — mock-gap в чужом коде, не регрессия).

## Поведение

На шаге `yt_6` (create-меню), если триггеры не найдены **и** `_premium_dismiss_enabled()` **и** `_yt_is_premium_promo(ui2)`:
- Back ×2 (только Back, без тапов по экрану → ноль риска платной подписки);
- **4 safety-гарда** перед ре-тапом: (1) промо ушло по валидному dump'у; (2) пустой dump ≠ доказательство снятия; (3) положительное подтверждение `foreground == YouTube` (None/'' → recovery); (4) финальная проверка dump'а перед тапом (валиден И не-промо); + ранний успех без ре-тапа, если меню уже открыто;
- ре-тап «+» → re-verify по тем же `verify_triggers`;
- не снялось → fail с `yt_create_menu_premium_blocking` (не маскарад под `yt_create_menu_not_reached`).
Kill-switch `YT_PREMIUM_DISMISS_ENABLED` (default ON). Инертно на happy-path и для IG/TT (только ветка промаха strict_verify).

## Процесс

brainstorm → spec → plan → subagent-driven реализация (implementer + спец-ревью + code-quality ревью на каждую из 4 кодовых задач). codex review: 3 раунда по спеке/плану (4 бага безопасности) + 2 раунда по реальному коду (`verify_triggers` passthrough; ранний успех без ре-тапа) → 0 P1/P2.

## Деплой-нюанс (реконсиляция)

Разработка велась в изолированном клоне `/home/claude-user/autowarm-wp132-dev` (origin = локальный путь, без auto-push hook). На момент деплоя прод `account_switcher.py` уже **уехал** с `bd8c6a5` на `862ce81` (чужие коммиты: WP #105 R2 IG dumpsys + WP #130 TT fg-guard). Слепая перезапись затёрла бы их. Решение: `git rebase` моих 6 коммитов на `862ce81` (чисто, регионы не пересеклись — мои YT-методы ~4499–4690, чужие правки в TT/IG ~228/2430/2788/4282/5304), прогон тестов на объединённом коде, TOCTOU-гард по хэшу перед копией, `.bak`-бэкап (`account_switcher.py.bak-wp132-20260522-112141`).

**Урок:** прод-`account_switcher.py` — горячая точка нескольких параллельных сессий; перед file-copy деплоем ОБЯЗАТЕЛЬНО сверять прод-хэш с базой и при дрейфе rebase'ить, а не перезаписывать.

## Откат

`export YT_PREMIUM_DISMISS_ENABLED=0` (мгновенно, без кода) или восстановить из `.bak`-копии.

## Что осталось (verify)

Понаблюдать 1–2 дня на проде. Запрос:
```sql
SELECT id, account, error_code,
       (SELECT count(*) FROM jsonb_array_elements(events) e
        WHERE e->'meta'->>'category' LIKE 'yt_premium_promo%') AS promo_events
FROM publish_tasks
WHERE platform='YouTube' AND created_at > now() - interval '12 hours'
ORDER BY id DESC LIMIT 30;
```
Ожидание: `yt_premium_promo_detected`→`yt_premium_promo_dismissed` на recovered-задачах; `yt_create_menu_premium_blocking` на нераскрытых (видно отдельно); снижение `yt_create_menu_not_reached` от промо-кейсов.

Подсигнатура B (камера TikTok после «+») — отдельная разведка, вне scope.
