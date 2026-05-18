# WP #93 — TT switch blocked by "Необходимо обновить аккаунт" modal: detect + classify + account_block

**Status:** design, 2026-05-18.
**Branch:** `feat/wp93-tt-picker-wrong-row` (rmbrmv/contenthunter).
**Source WP:** [#93](https://openproject.contenthunter.ru/work_packages/93) (переопределена 2026-05-18 — исходная гипотеза "picker tap не туда" не подтвердилась).
**Related ship:** WP #67 Layer 2 ([PR #70](https://github.com/GenGo2/delivery-contenthunter/pull/70), 2026-05-18) — содержит regression-строку whitelist, удаляемую этим WP.

## 1. Контекст

После выката WP #67 Layer 2 (2026-05-18 14:15 UTC) re-queued task **7372** (account `expertcontentlab`, raspberry 5) показал паттерн, который изначально интерпретировался как "picker tap попал не в тот ряд". Разбор UI-дампов опроверг эту гипотезу.

### Что реально происходит

| Шаг | UI dump | Содержимое |
|---|---|---|
| picker открыт | `tt_3_pick_account_*.xml` | bottomsheet ровно 3 строки: `serafima_liliyins`, `expertcontentlab` [Y=1573..1776], `liliyya_roshchina`. Target ровно посередине, без скролла. Все clickable. |
| после tap | `tt_4_target_profile_*.xml` | полноэкранная **блокирующая модалка** TT: heading «Необходимо обновить аккаунт», body «Чтобы усилить защиту, перед переключением между аккаунтами привяжите номер телефона или эл. почту…», buttons «Привязать номер телефона или эл. почту» / **«Не сейчас»** |
| после «Не сейчас» | `tt_4_target_profile_after_modal_dismiss_*.xml` | НЕ профиль `expertcontentlab`, а **feed** TT с автором случайного видео в sidebar (`Профиль ᵂᴴᴵᵀᴱ ＢＩＴＡ`, `Подписаться на ᵂᴴᴵᵀᴱ ＢＩＴＡ`, `Поставить лайк. Число лайков: 15,2 тыс.`) |

**Вывод:** picker tap отработал корректно. TT перехватил переключение блокирующей модалкой. Кнопка «Не сейчас» в этом конкретном диалоге = **refusal switch** (TT отменяет переход и выкидывает на feed), а не nuisance-dismiss.

### Layer 2 regression

`_TT_POST_SWITCH_DISMISSIBLE_MODALS` (account_switcher.py:223-226) включает запись:

```python
('Привязать номер телефона или эл. почту', 'Не сейчас'),
```

`title_substr` матчится по тексту BUTTON, а реальный heading модалки — «Необходимо обновить аккаунт». Layer 2 видит совпадение и нажимает «Не сейчас», получая refusal switch. Эта строка должна быть удалена.

### Системность

`tt_4_target_profile_*.xml` имеют идентичные MD5 на 2 task'ах (`2ac4a9a9e9722f1097e5b33ea162d575` для tasks 6786 и 7372). Это **системная** блокирующая модалка TT для аккаунтов без верифицированного контакта, не device-specific. До Layer 2 4 task'а (6514, 6631, 6704, 6786) фейлились с `error_code='tt_post_switch_verify_unrecoverable'` по тому же сценарию.

## 2. Цели и не-цели

### Цели
- Распознавать блокирующую pre-switch модалку TT по heading + clickable refusal button сразу после tap по picker-row.
- Эмитить специфичный `error_code='tt_switch_blocked'` для триажа и аналитики.
- Записывать `factory_reg_accounts.tt_block` с reason='phone_or_email_link_required' (аудит-трейл для оператора через `account_blocks` API).
- Удалить regression-строку из Layer 2 whitelist одним PR.

### Не-цели (YAGNI)
- Preflight skip в publisher по `is_blocked()` — existing IG human_check pattern его не имеет; retry-стоимость ~2min sub-attempt; добавление skipper'а раздувает scope.
- Generic blocking-modal taxonomy для IG/YT — других evidence нет.
- Cooldown / auto-unblock — `account_blocks` API сейчас unblock'ит ручным SQL (`scripts/unblock_account.sql`), сохраняем consistency.
- UI для разблокировки — отдельный backlog, не блокирует фикс.
- "Привязать номер телефона или эл. почту" как auto-action — требует SMS/email верификации, не автоматизируется.

## 3. Архитектура

Detector вставляется после `dump_ui` сразу за tap по picker-row, до `_post_switch_verify_handle`. На матч — fail-fast по IG human_check паттерну (`account_switcher.py:1474..1495`).

```
AccountSwitcher._switch_tiktok (per attempt):
  ...
  _find_and_tap_account(target, ...)             # tap picker row
  time.sleep(AFTER_SWITCH_WAIT_S)
  xml_after_pick = self.p.dump_ui(retries=1)     # existing
  self._save_dump('tt_4_target_profile', xml)    # existing (uploads to S3)
  self._maybe_screenshot(label)                  # existing
  [NEW]
  blocked = _tt_detect_switch_blocking_modal(xml_after_pick)
  if blocked is not None:
      heading, button, reason = blocked
      self.p.log_event('error',
          f'TT switch blocked by modal: {heading!r}',
          meta={'category': 'tt_switch_blocked',
                'reason': reason,
                'heading_substr': heading,
                'button_substr': button,
                'target': target,
                'attempt': attempt + 1,
                'step': 'tt_switch_blocked'})
      try:
          acc_id = account_blocks.set_block_by_username(
              target, 'tt', reason=reason,
              publish_task_id=self.p.task_id,
              step='tt_switch_blocked',
              last_seen_screen='tt_4_target_profile',
              heading_substr=heading)
      except Exception as be:
          log.warning(f'switcher.tt.set_block_failed: {be}')
          acc_id = None
      try:
          notifier.notify_escalation(
              f'tt_switch_blocked_{reason}',
              f'TT требует {("привязки номера/email" if reason == "phone_or_email_link_required" else reason)} для account={target}',
              f'task_id={self.p.task_id} factory_id={acc_id} step=tt_switch_blocked')
      except Exception as ne:
          log.warning(f'switcher.tt.notify_failed: {ne}')
      return self._fail(
          f'tt switch blocked (reason={reason})',
          step='tt_switch_blocked')
  [/NEW]
  status, current = self._post_switch_verify_handle(target, xml_after_pick, ...)
  ...
```

## 4. Components

### 4.1 Новая module-level константа (`account_switcher.py`, рядом с `_TT_POST_SWITCH_DISMISSIBLE_MODALS`)

```python
# WP #93 2026-05-18 — блокирующие pre-switch модалки.
# Формат: (heading_substr, refusal_button_substr, block_reason).
# Match-правило: heading_substr содержится в элементе class=TextView,
# clickable=false, лежащем в верхней половине модалки; refusal_button
# содержится в элементе class=Button, clickable=true.
# Защита от Layer 2 ловушки, где title_substr матчился по тексту BUTTON.
_TT_SWITCH_BLOCKING_MODALS: tuple[tuple[str, str, str], ...] = (
    ('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required'),
)
```

### 4.2 Новый module-level helper (`account_switcher.py`)

```python
def _tt_detect_switch_blocking_modal(
    xml: str,
) -> Optional[tuple[str, str, str]]:
    """Return (heading_substr, button_substr, reason) if modal matches, else None.

    Matches when there exists a TextView element (NOT clickable) whose label
    contains heading_substr, AND a Button element (clickable) whose label
    equals button_substr (case-insensitive, trimmed). Both must coexist
    in the same dump. This is intentionally stricter than Layer 2 to avoid
    matching button labels as headings.
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)
    for heading, button, reason in _TT_SWITCH_BLOCKING_MODALS:
        heading_lc = heading.lower()
        button_lc = button.lower()
        has_heading = any(
            heading_lc in (el.label or '').lower()
            and not el.clickable
            and 'TextView' in (el.cls or '')
            for el in elements
        )
        has_button = any(
            (el.label or '').strip().lower() == button_lc
            and el.clickable
            and 'Button' in (el.cls or '')
            for el in elements
        )
        if has_heading and has_button:
            return (heading, button, reason)
    return None
```

(Точные имена полей `el.label`, `el.clickable`, `el.cls`  — следовать существующему API `parse_ui_dump`. В plan-фазе сверим.)

### 4.3 Изменение `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (`account_switcher.py:225`)

```python
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # WP #93 2026-05-18 — УДАЛЕНО: модалка блокирующая, не nuisance.
    # Перенесено в _TT_SWITCH_BLOCKING_MODALS.
    # ('Привязать номер телефона или эл. почту', 'Не сейчас'),
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

### 4.4 Вставка detector в `_switch_tiktok`

Точка вставки: в `account_switcher.py` после `self._save_dump(label, xml_after_pick)` и `self._maybe_screenshot(label)` (около строки ~2562), ДО вызова `self._post_switch_verify_handle(...)`. Внутри цикла `for attempt in range(MAX_PICK_ATTEMPTS)` — detector работает для каждого attempt'а (модалка может появиться на любом).

### 4.5 Новый error_code в `publisher_kernel.py:159` map

```python
'tt_switch_blocked': 'tt_switch_blocked',  # WP #93 2026-05-18
```

### 4.6 Что НЕ меняется
- `account_blocks.py` — переиспользуем `set_block_by_username` без изменений.
- `notifier.py` — переиспользуем `notify_escalation` без изменений.
- Layer 1 (`@`-handle priority) — не трогаем.
- Layer 2 (`_tt_try_dismiss_post_switch_modal`, probe-sites) — только удаление одной строки whitelist; helper, telemetry, kill-switch остаются.

## 5. Data flow

### 5.1 Сценарий A — blocking modal detected
1. `_find_and_tap_account(target)` тапает picker-row корректно.
2. `dump_ui` + `_save_dump('tt_4_target_profile', xml)` сохраняет XML на S3.
3. `_tt_detect_switch_blocking_modal(xml)` возвращает `('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required')`.
4. `log_event('error', category='tt_switch_blocked', meta={...})` — первое действие, гарантирует аудит-трейл.
5. `account_blocks.set_block_by_username(target, 'tt', reason='phone_or_email_link_required', publish_task_id, step='tt_switch_blocked', last_seen_screen='tt_4_target_profile', heading_substr)` — best-effort.
6. `notifier.notify_escalation(...)` — best-effort.
7. `self._fail('tt switch blocked (reason=...)', step='tt_switch_blocked')` → publisher fail-path resolver видит category и эмитит финальный `error_code='tt_switch_blocked'`.

### 5.2 Сценарий B — happy path
1. tap + dump + `_save_dump`.
2. `_tt_detect_switch_blocking_modal(xml)` → None.
3. `_post_switch_verify_handle` → status='match'.
4. Switch успешен → продолжается publish flow.

### 5.3 Сценарий C — nuisance modal (existing flow)
1. tap + dump + `_save_dump`.
2. `_tt_detect_switch_blocking_modal(xml)` → None (heading «Сохранить данные для входа» НЕ в blocking whitelist).
3. `_post_switch_verify_handle` → status='unknown'.
4. `_tt_handle_post_switch_unknown` → Layer 1 → Layer 2 dismiss «Сохранить данные для входа» → re-verify → match.

### 5.4 Edge cases
- **`set_block` fails** (DB недоступна): warn, fail с error_code всё равно эмитим. Аудит-трейл в `tt_block` теряем, но event с `category='tt_switch_blocked'` уже в `publish_tasks.events`.
- **`notify_escalation` fails**: warn, fail не блокируется. Telemetry event сохранён.
- **dump fails** (S3 ↑network): `_save_dump` уже обрабатывает best-effort. Detector использует `xml` из памяти. URL в event meta может быть None.
- **аккаунт уже blocked** ранее: `set_block_by_username` перезаписывает payload (existing IG human_check behavior) — last evidence свежее, OK.
- **detector false positive**: низкий риск — heading «Необходимо обновить аккаунт» специфичен, требование обоих сигналов (TextView+heading И Button+button-text) делает совпадение строгим. Unit-тест на real prod dump task 7372.
- **detector false negative** (новый heading, не в whitelist): остаточный `tt_post_switch_verify_unrecoverable` всплывёт в 24h soak; добавляем строку в `_TT_SWITCH_BLOCKING_MODALS` (тот же паттерн что и для Layer 2 расширения).

## 6. Error handling & telemetry

### 6.1 Новый event
| field | value |
|---|---|
| type | `error` |
| message | `TT switch blocked by modal: 'Необходимо обновить аккаунт'` (или подобное) |
| meta.category | `tt_switch_blocked` |
| meta.reason | `phone_or_email_link_required` |
| meta.heading_substr | `Необходимо обновить аккаунт` |
| meta.button_substr | `Не сейчас` |
| meta.target | `expertcontentlab` |
| meta.attempt | `1` (1-indexed) |
| meta.step | `tt_switch_blocked` |

### 6.2 Новый error_code
`tt_switch_blocked` — через category-to-error_code map в `publisher_kernel.py`.

### 6.3 account_blocks payload (`factory_reg_accounts.tt_block` JSONB)
```json
{
  "reason": "phone_or_email_link_required",
  "detected_at": "2026-05-18T15:30:00+00:00",
  "publish_task_id": 7372,
  "step": "tt_switch_blocked",
  "last_seen_screen": "tt_4_target_profile",
  "heading_substr": "Необходимо обновить аккаунт"
}
```

### 6.4 Notifier escalation
- key: `tt_switch_blocked_phone_or_email_link_required`
- title: `TT требует привязки номера/email для account=<target>`
- body: `task_id=<id> factory_id=<acc_id> step=tt_switch_blocked`

### 6.5 Best-effort isolation
- `log_event` эмитится **первым**, до `set_block` / `notify_escalation`. Telemetry устойчив к downstream-сбоям.
- `set_block_by_username` обёрнут try/except → log.warning. `acc_id` может быть None.
- `notify_escalation` обёрнут try/except → log.warning.
- Если `acc_id is None`, в notify body будет `factory_id=None` — acceptable, оператор увидит account по username.

### 6.6 Kill-switch / rollback
- Trivial: `_TT_SWITCH_BLOCKING_MODALS = ()` → helper всегда возвращает None → flow идентичен pre-fix. Тот же паттерн что в Layer 2.
- Revert строки из Layer 2 — back-compatible: меньше dismiss-попыток, не ломает happy-path.
- Откат всего PR — `git revert`; account_blocks записи остаются (read-only data, не мешают).

## 7. Testing

### 7.1 Unit-тесты (новый файл `tests/test_tt_switch_blocking_modal.py`)

| тест | вход | ожидание |
|---|---|---|
| `test_detect_known_blocking_modal_from_prod_dump` | реальный XML task 7372 (`tt_4_target_profile_7372.xml` fixture) | возвращает `('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required')` |
| `test_detect_returns_none_on_feed` | реальный feed XML (`tt_feed_after_modal_dismiss_7372.xml`) | `None` |
| `test_detect_returns_none_on_profile` | реальный profile XML (`tt_profile_screen_7372.xml`) | `None` |
| `test_detect_button_only_no_match` | synthetic XML только с кнопкой «Не сейчас» без heading | `None` |
| `test_detect_heading_as_button_no_match` | synthetic XML где «Необходимо обновить...» это Button, не TextView | `None` (защита от Layer 2 ловушки) |
| `test_detect_heading_only_no_match` | synthetic XML только с heading, без clickable «Не сейчас» | `None` |
| `test_detect_empty_xml_returns_none` | `''` | `None` |

### 7.2 Integration-тесты (тот же файл, mock proxy)

| тест | сценарий | ожидание |
|---|---|---|
| `test_switcher_blocked_emits_event_and_fails` | detector matched | в `events` есть category=`tt_switch_blocked`; `_fail` вызван с step=`tt_switch_blocked` |
| `test_switcher_blocked_calls_set_block_with_expected_payload` | mock `account_blocks` | `set_block_by_username(target, 'tt', reason='phone_or_email_link_required', publish_task_id=..., step='tt_switch_blocked', last_seen_screen='tt_4_target_profile', heading_substr=...)` вызван 1 раз |
| `test_switcher_blocked_set_block_failure_doesnt_break_fail` | mock `set_block` raises | `_fail` всё равно вызван, event эмитнут, log.warning записан |
| `test_switcher_blocked_calls_notify_escalation` | mock `notifier` | `notify_escalation` вызван с правильным key/title/body |
| `test_layer2_does_not_match_phone_email_button` | XML с heading «Необходимо обновить...» прогнан через Layer 2 dismiss | Layer 2 НЕ tap'ает (whitelist пуст для этой строки) |

### 7.3 Fixtures (commit'ятся в `tests/fixtures/`)

Скачивание с S3 URL'ов (см. publish_tasks.events для task 7372):
- `tt_switch_blocked_phone_email_7372.xml` — копия `task7372_switch_7372_tt_4_target_profile_1779114421.xml`
- `tt_feed_after_modal_dismiss_7372.xml` — копия `task7372_switch_7372_tt_4_target_profile_after_modal_dismiss_1779114431.xml`
- `tt_profile_screen_7372.xml` — копия `task7372_switch_7372_tt_2_profile_screen_1779114389.xml`

### 7.4 Smoke (post-deploy)
1. **Re-queue task 7372** (`expertcontentlab`) через `publish_queue` UPDATE → pending → dispatchPublishQueue создаст новый publish_task → ожидаем `status='failed'`, `error_code='tt_switch_blocked'`, event категории `tt_switch_blocked` в jsonb.
2. **Test publish известно-good account** (`just_clickpay`, без блокирующей модалки) → ожидаем `status='done'` или существующий happy-path failure. Happy-path не сломан.
3. **SQL-проверка**:
   ```sql
   SELECT tt_block FROM factory_reg_accounts WHERE tiktok_username='expertcontentlab';
   ```
   Ожидаем JSON с `reason='phone_or_email_link_required'`, `detected_at`, `publish_task_id`, `heading_substr`.

### 7.5 24h soak (deadline +24h post-deploy)
- `SELECT count(*) FROM publish_tasks WHERE error_code='tt_switch_blocked' AND created_at >= NOW() - INTERVAL '24 hours';` → ожидаем 3-5 (исторический baseline по 6514, 6631, 6704, 6786 за 2026-05-13..18).
- `SELECT count(*) FROM publish_tasks WHERE error_code='tt_post_switch_verify_unrecoverable' AND events::text NOT ILIKE '%phone_or_email_link_required%' AND created_at >= NOW() - INTERVAL '24 hours';` → ожидаем меньше чем pre-deploy baseline (отделили blocking-modal часть).
- Если новые `tt_post_switch_verify_unrecoverable` task'и имеют похожий XML паттерн (другой heading) → расширяем `_TT_SWITCH_BLOCKING_MODALS` одной строкой и тестом.

## 8. Артефакты

- WP #67 Layer 2 ship doc: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md`
- WP #93 evidence: task 7372 (raspberry 5, `expertcontentlab`, 2026-05-18 14:20 UTC); исторические подтверждения 6514, 6631, 6704, 6786.
- Существующий шаблон IG human_check: `account_switcher.py:1474..1495`, `publisher_base.py:4215..4240`.
- `account_blocks` API: `account_blocks.py` (set_block_by_username, is_blocked, get_block).

## 9. Открытые вопросы

- **Точное имя поля `parse_ui_dump`** возвращаемых элементов (`label` vs `text` vs `content_desc`, `cls` vs `class`) — сверить при написании implementation plan чтением `account_switcher.py` parse-helpers (уже используются в `_tt_try_dismiss_post_switch_modal`, тот же паттерн).
- **header_y_max** filtering для heading — не используется сейчас в спецификации, потому что bottomsheet с модалкой занимает большую часть экрана, и Y-фильтр не нужен; если в plan-фазе обнаружим heading в нижней половине экрана у других модалок — добавим Y-фильтр (например `y < 1500`) опционально.
