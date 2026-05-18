# TT post-switch promo-modal dismiss — SHIPPED 2026-05-18 (WP #67 Layer 2)

**WP:** [#67](https://openproject.contenthunter.ru/work_packages/67) (Ошибка)
**PR:** [GenGo2/delivery-contenthunter #70](https://github.com/GenGo2/delivery-contenthunter/pull/70) — squash-merge `aa11d63`
**Branch:** `worktree-wp67-tt-modal-dismiss-2026-05-18` (deleted on merge)
**Deploy:** `git pull --ff-only` в `/root/.openclaw/workspace-genri/autowarm` + `sudo pm2 restart autowarm` (2026-05-18 14:15 UTC)
**Layer 1 reference:** PR #62 (`433c5b2`) от 2026-05-14 — `@`-handle priority в `get_current_account_from_profile`

## Триаж — почему второй слой

После Layer 1 объём `tt_post_switch_verify_unrecoverable` упал с 16/день до 1–2/день. Status WP #67 ушёл в «Тестирование» 14.05. 18.05 переведён обратно в «В разработке» — за 4 суток (15-18 мая) пришло 5 residual fails, у которых иная картина (Layer 1 их не покрывает):

| task | rasp | account | failmsg | post-switch screen |
|---|---|---|---|---|
| 6514 | 8 | pure_oracle | `unknown header non-feed` | модалка «Привязать номер телефона или эл. почту» + «Не сейчас» |
| 6631 | 10 | tkachenko_health2 | `unknown header non-feed` | та же модалка |
| 6704 | 2 | swarovski_life | `unknown header non-feed` | та же модалка |
| 6786 | 5 | expertcontentlab | `unknown header non-feed` | та же модалка |
| 7307 | 9 | just_clickpay | `no profile after re-nav` | первый dump = feed → renav → модалка «Сохранить данные для входа» |

XML-дампы 4 «Привязать номер»-кейсов **байт-в-байт идентичны** (7603 bytes, текст «Не сейчас» на `y=1433`). Это не device-specific — TikTok periodically инжектит promo-модалку после переключения аккаунта.

## Root cause (Layer 2)

`_tt_handle_post_switch_unknown` (`account_switcher.py:4256`) различал только profile (verify=match/mismatch) и feed (`_is_tt_feed_after_pick=True` → renav). Третий экран (включая dismissable promo-модалки) попадал в `is_feed=False` → немедленный `_fail('unknown header non-feed')`. Промо-модалка закрывается стандартной кнопкой dismiss, после чего за ней открывается profile screen.

Task 7307 двойной кейс: первый dump = feed (renav сработал), но после renav profile перекрыт другим promo-модалом → re-verify=unknown → `no profile after re-nav`.

## Что сделано (Variant A — single-shot pre-feed-probe)

**Whitelist (module-level, `account_switcher.py:223`):**
```python
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    ('Привязать номер телефона или эл. почту', 'Не сейчас'),
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

**Detector (module-level helper, `account_switcher.py:383`):**
`_tt_try_dismiss_post_switch_modal(xml) -> Optional[tuple[str, str]]` — требует ОБА условия: title_substr `in el.label` И clickable элемент с `el.label.strip().lower() == button.lower()`. Pure function, no side effects.

**Recovery method (`AccountSwitcher._try_dismiss_and_redump`, line 4301):**
probe → tap_element → sleep(POST_TAP_WAIT_S=1.2) → dump_ui → save_dump → returns `(title, new_xml)` или None.

**2 probe-site вставки в `_tt_handle_post_switch_unknown`:**
- **Step 0a (pre-feed):** до `_is_tt_feed_after_pick`. Match → re-verify → `recovered` (match) / fall through с новым XML (unknown) / `mismatch` (mismatch).
- **Step 3a (post-renav):** после `_post_switch_verify_handle(xml_after_renav)`, если status='unknown'. Match → `recovered`; иначе fall through к existing fail.

Cap=1 dismiss/site, total ≤2/handle. Никаких циклов.

## Telemetry (3 новых event)

| event_name | type | meta payload |
|---|---|---|
| `tt_post_switch_modal_dismiss_attempted` | `info` | `title_substr, button_text, probe_site ∈ {'pre_feed', 'post_renav'}, target, attempt` |
| `tt_post_switch_recovered_via_modal_dismiss` | `account_switch` | `title_substr, target, current, probe_site, attempt` |
| `tt_post_switch_modal_dismiss_no_recovery` | `warning` | `title_substr, target, probe_site, reverify_status ∈ {'tap_failed', 'unknown', 'mismatch'}` |

**Никаких новых error_code:** существующие `tt_post_switch_verify_unrecoverable: unknown header non-feed` / `no profile after re-nav` сохранены. До/после фикса различаются наличием `_attempted` события до fail'а.

## Tests

`tests/test_account_switcher_modal_dismiss.py` — 16 tests passed:

**10 unit (`_tt_try_dismiss_post_switch_modal`):**
1. Whitelist seeded with 2 entries.
2. modal_phone_email_6514.xml → match.
3. modal_save_login_7307_renav.xml → match.
4. profile_5817 → None (negative).
5. feed_no_sheet → None (negative).
6. empty XML → None.
7. unparseable XML → None.
8. title-only without button → None.
9. button-only without title → None.
10. button not clickable → None.

**6 integration (`_tt_handle_post_switch_unknown`):**
1. pre_feed dismiss happy path (modal → dismiss → match).
2. post_renav dismiss happy path (feed → renav → modal → dismiss → match).
3. whitelist miss → existing fail path.
4. modal matched, re-verify still unknown → fall through.
5. modal matched, re-verify mismatch → return `mismatch`.
6. tap_element=False → tap_failed event + fall through.

**Full switcher suite:** 214/215 passed (1 pre-existing `test_yt_happy_path_returns_accounts` known baseline fail). 0 new regressions. Codex review (full diff via stdin) — 0 P1/P2.

## Smoke verdict (post-deploy)

Re-queued 2 из 5 residual задач через `publish_queue` reset (memory `reference_publish_requeue_path`):

| new task | account | status | dismiss_attempts | recovered_via_modal | no_recovery | result |
|---|---|---|---:|---:|---:|---|
| 7373 | just_clickpay | `done` | 0 | 0 | 0 | ✅ published — модалка не появилась, happy-path не сломан |
| 7372 | expertcontentlab | `failed` | 1 | 0 | 1 | ⚠️ probe сработал корректно (XML 7603→19628 байт, модалка закрылась), но post-dismiss попали на чужой профиль «ᵂᴴᴵᵀᴱ ＢＩＴＡ» |

**7372 — НЕ регрессия.** Probe + dismiss отработали как спроектированы (`tt_post_switch_modal_dismiss_attempted` + `tt_post_switch_modal_dismiss_no_recovery` события с `reverify_status='unknown'` + `title_substr='Привязать номер...'`). Старый код тут тоже бы fail'нулся, но без observability. Открытый picker-bug — отдельный WP #93 (см. follow-ups).

## Rollback

Trivial: `_TT_POST_SWITCH_DISMISSIBLE_MODALS = ()` → helper всегда None → оба probe site no-op → identical к pre-fix. Kill-switch без env-var.

## 24h soak (deadline ~2026-05-19 14:15 UTC)

```sql
WITH last_fail AS (
  SELECT pt.id, pt.created_at,
    (SELECT e->>'msg' FROM jsonb_array_elements(pt.events) WITH ORDINALITY x(e,ord)
     WHERE e->>'type'='fail' ORDER BY ord DESC LIMIT 1) AS failmsg,
    (SELECT count(*) FROM jsonb_array_elements(pt.events) e
     WHERE e->>'msg' LIKE '%tt_post_switch_modal_dismiss_attempted%') AS dismiss_attempts
  FROM publish_tasks pt
  WHERE pt.platform='TikTok' AND pt.status='failed' AND pt.testbench=false
    AND pt.created_at >= NOW() - INTERVAL '24 hours'
)
SELECT
  count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%') AS verify_fails_24h,
  count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%'
                     AND dismiss_attempts = 0) AS verify_fails_no_dismiss_24h
FROM last_fail;
```

Acceptance:
- `verify_fails_24h` ≤ 1 (целевой 0; учесть picker-bug WP #93 — может оставить 1).
- `verify_fails_no_dismiss_24h ≥ 1` сигналит про новую модалку → расширить whitelist одной строкой.

## Follow-ups

- **WP #93 (новый):** picker-bug — после dismiss task 7372 попали на чужой профиль (account picker tap не туда). Завести когда соберётся ≥2 evidence.
- **Minor test:** добавить `post_renav dismiss → reverify=mismatch` для симметрии (низкий приоритет).
- **Refactor (если IG/YT тоже появится):** переименовать `_try_dismiss_and_redump` → `_tt_try_dismiss_and_redump` для platform-prefix consistency.

## Артефакты

- Spec: `docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md`
- Plan: `docs/superpowers/plans/2026-05-18-tt-post-switch-modal-dismiss-plan.md`
- Triage (входной): `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`
- Memory: `project_tt_post_switch_modal_dismiss_shipped`
