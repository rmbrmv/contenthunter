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
  xml_after_pick = self.p.dump_ui(retries=1)        # existing
  self._save_dump(label, xml_after_pick)            # existing (uploads to S3; label = 'tt_4_target_profile' or retry suffix)
  self._maybe_screenshot(label)                     # existing
  [NEW]
  # Defensive try/except: detector в hot-path не должен ломать switch
  # из-за корявого dump'а или regex-edge-case. parse_ui_dump уже
  # обрабатывает ParseError, но любой другой Exception (re.error и т.п.)
  # тут гасим, продолжаем на старый verify-flow.
  try:
      blocked = _tt_detect_switch_blocking_modal(xml_after_pick)
  except Exception as de:
      log.warning(f'switcher.tt.detect_blocking_modal_failed: {de}')
      blocked = None
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
          # set_block_by_username(username, platform, reason, **context) —
          # **context kwargs принимаются и складываются в JSONB payload
          # (см. account_blocks.py:51 set_block signature, существующий
          # IG human_check call в publisher_base.py:4217).
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
# Match-правило: heading_substr содержится в элементе с clickable=false
# (heading — текст модалки, не нажимается); refusal_button содержится в
# элементе с clickable=true (нажимаемая кнопка). Защита от Layer 2 ловушки,
# где title_substr матчился по тексту BUTTON: heading-проверка отвергает
# clickable элементы, поэтому совпадение по button-тексту невозможно.
# (UIElement в parse_ui_dump хранит text/content_desc/clickable/bounds —
# поля class нет, отличаем headings от buttons по clickable.)
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

    Matches when there exists a NON-clickable element whose label contains
    heading_substr (heading), AND a clickable element whose label equals
    button_substr (case-insensitive, trimmed). Both must coexist in the
    same dump. Heading-check requires NON-clickable explicitly to avoid
    the Layer 2 trap (where title_substr matched a button label and led to
    nuisance dismiss of a refusal button).
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)
    if not elements:
        return None
    for heading, button, reason in _TT_SWITCH_BLOCKING_MODALS:
        heading_lc = heading.lower()
        button_lc = button.lower()
        has_heading = any(
            heading_lc in el.label.lower() and not el.clickable
            for el in elements
        )
        has_button = any(
            el.clickable and el.label.strip().lower() == button_lc
            for el in elements
        )
        if has_heading and has_button:
            return (heading, button, reason)
    return None
```

`UIElement` (account_switcher.py:298) хранит `text`, `content_desc`, `clickable`, `bounds`; `el.label` = `(text + ' ' + content_desc).strip()`. Поля `cls` нет — отличие heading от button через `clickable`.

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

### 4.5 Новый error_code в `publisher_kernel.py` step→error_code map

`publisher_kernel.py` содержит **step → error_code** mapping (см. существующие `'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable'`, `'ig_human_check_required': 'ig_human_check_required'`). Добавляем:

```python
'tt_switch_blocked': 'tt_switch_blocked',  # WP #93 2026-05-18
```

Это работает потому, что в §3 мы вызываем `self._fail(..., step='tt_switch_blocked')` — resolver видит `step` и через map даёт `error_code='tt_switch_blocked'`. Event'овая `meta.category='tt_switch_blocked'` сохраняется параллельно и подхватывается через fallback-путь `_resolve_publish_fail_category` (см. publisher_base.py:1871) если step-mapping почему-то промахнётся.

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
- **dump fails** (S3 / network): `_save_dump` уже обрабатывает best-effort. Detector использует `xml_after_pick` из памяти. URL в event meta может быть None.
- **аккаунт уже blocked** ранее: `set_block_by_username` перезаписывает payload (existing IG human_check behavior) — last evidence свежее, OK.
- **detector false positive**: низкий риск — heading «Необходимо обновить аккаунт» специфичен, требование обоих сигналов (NON-clickable элемент с heading-substr И clickable элемент с button-text) делает совпадение строгим. Unit-тест на real prod dump task 7372.
- **detector false negative — heading в clickable parent**: Android dumps в некоторых случаях сворачивают text внутри clickable FrameLayout/ViewGroup parent'а; тогда heading_substr вернёт `clickable=true` и не сматчится. В нашем prod-dump task 7372 heading TextView clickable=false подтверждён — для known fixture работает. Если в 24h soak увидим новые task'и с XML где heading «Необходимо обновить...» сидит в clickable parent — расширяем helper: добавим second pass который игнорирует clickable-фильтр heading'а (но строгое равенство для button сохраняем).
- **detector false negative** (новый heading, не в whitelist): остаточный `tt_post_switch_verify_unrecoverable` всплывёт в 24h soak; добавляем строку в `_TT_SWITCH_BLOCKING_MODALS` (тот же паттерн что и для Layer 2 расширения).
- **detector raises exception** (re.error, malformed elements): обёрнут try/except в call-site (§3), `blocked = None`, продолжаем на старый verify-flow. Telemetry-warning логируется.

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

Pre-deploy baseline (за 2026-05-13..18, выборка по `error_code='tt_post_switch_verify_unrecoverable'`):
- 24 task'а за 7 дней (~3-4/день в среднем).
- Из них 4 идентифицированы как «блокирующая модалка обновления аккаунта» (6514, 6631, 6704, 6786) — ~0.6/день.

После деплоя:
- `SELECT count(*) FROM publish_tasks WHERE error_code='tt_switch_blocked' AND created_at >= NOW() - INTERVAL '24 hours';` → ожидаем 0-2 (большинство этих аккаунтов уже среди 4 evidence, добавлены в tt_block ранее retry'ями).
- `SELECT count(*) FROM publish_tasks WHERE error_code='tt_post_switch_verify_unrecoverable' AND created_at >= NOW() - INTERVAL '24 hours';` → ожидаем ≤ pre-deploy (3-4/день минус блокирующая часть).
- Если новые `tt_post_switch_verify_unrecoverable` task'и имеют похожий XML паттерн (другой heading) → расширяем `_TT_SWITCH_BLOCKING_MODALS` одной строкой и тестом.

## 8. Артефакты

- WP #67 Layer 2 ship doc: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md`
- WP #93 evidence: task 7372 (raspberry 5, `expertcontentlab`, 2026-05-18 14:20 UTC); исторические подтверждения 6514, 6631, 6704, 6786.
- Существующий шаблон IG human_check: `account_switcher.py:1474..1495`, `publisher_base.py:4215..4240`.
- `account_blocks` API: `account_blocks.py` (set_block_by_username, is_blocked, get_block).

## 9. Открытые вопросы

- **Y-фильтр для heading**: сейчас не используется — bottomsheet с модалкой занимает большую часть экрана и Y-фильтрация не нужна. Если в будущих evidence появятся модалки с heading в нижней половине экрана у других сценариев — добавим опциональный Y-фильтр (например `y < 1500`) в helper.
- **Notifier-rate-limit для уже-blocked аккаунтов**: каждый повторный attempt вызовет `notify_escalation` ещё раз. Если это создаст шум — обернуть escalation в проверку `if not is_blocked(acc_id, 'tt'): notify_escalation(...)`. Решение по факту первых 24h в проде.
- **Robust heading-detection**: spec фиксирует strict `clickable=false` для heading. Если 24h soak покажет XML edge-cases (heading в clickable parent), решаем: (a) ослабить heading-фильтр до «любой элемент с substr» при сохранении strict button=clickable; либо (b) добавить proximity-check (heading и button в одной модальной dialog-области по координатам).
