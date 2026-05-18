# 2026-05-18 — WP #93 SHIPPED: TT switch blocked by «Необходимо обновить аккаунт» modal

**PR:** [GenGo2/delivery-contenthunter#75](https://github.com/GenGo2/delivery-contenthunter/pull/75) — squash `52efe66`, merged 19:02 UTC.
**Spec + plan:** rmbrmv/contenthunter main (squash `6bdedcb14`).
**Deploy:** `git pull origin main` + `pm2 restart autowarm` на prod `/root/.openclaw/workspace-genri/autowarm/` сразу после merge.
**OpenProject:** WP #93 → Готово (status 12).

## Что было не так

WP #93 изначально описывала «picker tap попадает не в тот ряд → открывается чужой профиль». Разбор UI-дампов task 7372 (account `expertcontentlab` на raspberry 5) опроверг гипотезу:

- `tt_3_pick_account.xml`: bottomsheet ровно 3 строки, target `expertcontentlab` ровно посередине [Y=1573..1776], без скролла, clickable. Picker tap отработал корректно.
- `tt_4_target_profile.xml` (после tap): полноэкранная блокирующая модалка с heading **«Необходимо обновить аккаунт»** + body «Чтобы усилить защиту, перед переключением между аккаунтами привяжите номер телефона или эл. почту…» + buttons «Привязать номер телефона или эл. почту» / **«Не сейчас»**.
- `tt_4_target_profile_after_modal_dismiss.xml` (после «Не сейчас»): НЕ профиль `expertcontentlab`, а feed TT с автором случайного видео в sidebar.

**Реальная причина:** TT перед самим переключением показывает блокирующую модалку требующую привязки контакта. «Не сейчас» = refusal switch (TT отменяет переход и выкидывает на feed), не nuisance-dismiss. WP #67 Layer 2 whitelist по ошибке матчил эту модалку через `title_substr` по тексту BUTTON («Привязать номер…») при реальном heading «Необходимо обновить аккаунт», и нажимал «Не сейчас» каждый attempt.

Идентичный паттерн в 4 task'ах за 2026-05-13..18 (md5 `2ac4a9a9e9722f1097e5b33ea162d575` на task 6786 и 7372): 6514, 6631, 6704, 6786 — все фейлились с `tt_post_switch_verify_unrecoverable` по тому же сценарию. Plus post-Layer-2 7372 (smoke).

## Что сделано

1. **Новая константа** `_TT_SWITCH_BLOCKING_MODALS: tuple[tuple[str, str, str], ...]` в `account_switcher.py` (формат `(heading_substr, refusal_button, reason)`). Первая запись: `('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required')`.
2. **Новый helper** `_tt_detect_switch_blocking_modal(xml)` — pure XML parser. Match-правило: heading_substr в элементе с `clickable=false` И refusal_button в элементе с `clickable=true` (exact-equality после `.strip().lower()`). Defensive try/except вокруг `parse_ui_dump`.
3. **Новый method** `_maybe_handle_switch_blocking_modal(xml_after_pick, target, attempt)` в `AccountSwitcher`. На match → `log_event(category='tt_switch_blocked', meta={...})` → best-effort `account_blocks.set_block_by_username(target, 'tt', reason='phone_or_email_link_required', publish_task_id, step='tt_switch_blocked', last_seen_screen='tt_4_target_profile', heading_substr)` → best-effort `notifier.notify_escalation` → `return self._fail(step='tt_switch_blocked')`. Pattern скопирован с IG human_check (`publisher_base.py:4451`).
4. **Call-site** в `_switch_tiktok` сразу после `_save_dump(label, xml_after_pick)` / `_maybe_screenshot(label)`, до `_post_switch_verify_handle`. Внутри цикла `for attempt in range(MAX_PICK_ATTEMPTS)` — fail-fast на каждом attempt.
5. **Revert** regression-строки `('Привязать номер телефона или эл. почту', 'Не сейчас')` из `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (Layer 2 whitelist). `('Сохранить данные для входа', 'Не сейчас')` оставлена.
6. **publisher_kernel** step→error_code mapping: `'tt_switch_blocked': 'tt_switch_blocked'` (identity).
7. **Тесты:** 14 новых (8 unit + 5 integration + 1 layer2-no-match) на real prod fixtures из task 7372. 6 WP #67 тестов переориентированы на `save_login_7307` fixture (старая `phone_email_6514` fixture теперь negative — Layer 2 не матчит).
8. **Codex review** specs/plan — 3 раунда до 0 P1.

## Что осталось

- **24h soak deadline ~2026-05-19 19:02 UTC.** Acceptance:
  - `count(error_code='tt_switch_blocked' AND created_at >= NOW() - 24h)` 0-2 (большинство блокированных аккаунтов сядут в `tt_block` после первого retry).
  - `count(error_code='tt_post_switch_verify_unrecoverable' AND created_at >= NOW() - 24h)` ≤ pre-deploy baseline (3-4/день — минус blocking-modal часть).
- **Smoke на re-queued task 7372** — opt-in (можно дождаться естественного появления).
- **Если в soak появятся новые `tt_post_switch_verify_unrecoverable`** с похожим XML паттерном (другой heading) — расширить `_TT_SWITCH_BLOCKING_MODALS` одной строкой и тестом.
- **Operator workflow:** разблокировка аккаунта `expertcontentlab` (и любых других попавших в `tt_block`) — вручную через `scripts/unblock_account.sql` после привязки номера/email в TT.

## Kill-switch

`_TT_SWITCH_BLOCKING_MODALS = ()` в `account_switcher.py` → helper всегда None → flow идентичен pre-fix. Single-line patch.

## Связки

- WP #67 Layer 2 shipped doc: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md` (источник regression-строки удалённой в этом PR).
- account_blocks API: `account_blocks.py` (set_block_by_username, is_blocked, get_block) — переиспользован без изменений.
- IG human_check шаблон: `account_switcher.py:1474..1495` + `publisher_base.py:4451..4475` (заимствованный паттерн).
