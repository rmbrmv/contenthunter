# TT post-switch verify — dismiss known promo-modals (WP #67 Layer 2)

**Дата:** 2026-05-18
**WP:** [#67](https://openproject.contenthunter.ru/work_packages/67) — `tt_post_switch_verify_unrecoverable`
**Слой:** Layer 2 (Layer 1 — `@`-handle priority — зашиплен 2026-05-14, PR [#62](https://github.com/GenGo2/delivery-contenthunter/pull/62))
**Файл изменений:** `account_switcher.py`
**Связанные документы:**
- `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md` — триаж дня, выбор бага
- `docs/superpowers/specs/2026-05-14-tt-post-switch-verify-handle-priority-design.md` — Layer 1 (shipped)

## Контекст и проблема

После выката Layer 1 (приоритет `@`-логина в `get_current_account_from_profile`) объём
`tt_post_switch_verify_unrecoverable` упал с 16/день до 1–2/день. Остаточные кейсы
(5 шт. за 2026-05-15..18) имеют **другую причину**: после переключения аккаунта
TikTok рендерит не profile feed, а блокирующий promo-диалог.

### Evidence

UI-дампы 5 residual задач (`tt_4_target_profile` stage):

| task | rasp | account | дата | экран после pick | failmsg |
|---|---|---|---|---|---|
| 6514 | 8 | pure_oracle | 2026-05-15 12:55 | модалка «Привязать номер телефона или эл. почту» + «Не сейчас» | `unknown header non-feed` |
| 6631 | 10 | tkachenko_health2 | 2026-05-15 16:39 | та же модалка | `unknown header non-feed` |
| 6704 | 2 | swarovski_life | 2026-05-16 07:08 | та же модалка | `unknown header non-feed` |
| 6786 | 5 | expertcontentlab | 2026-05-18 06:13 | та же модалка | `unknown header non-feed` |
| 7307 | 9 | just_clickpay | 2026-05-18 10:15 | первый dump = feed → renav → модалка «Сохранить данные для входа» + «Не сейчас» | `no profile after re-nav` |

XML-дампы 4 «Привязать номер»-кейсов **байт-в-байт идентичны** (7603 байт), что
подтверждает: это один и тот же стандартный TT-модал, не device-specific.

### Корневая причина (Layer 2)

`_tt_handle_post_switch_unknown` (`account_switcher.py:4256`) различает только два
post-pick экрана: profile (verify=match/mismatch) и feed (`_is_tt_feed_after_pick=True`
→ renav). Любой третий экран — включая закрываемые promo-модалки — попадает в ветку
`is_feed=False` → немедленный `_fail('unknown header non-feed')`. Промо-модалки
закрываются стандартной кнопкой dismiss, после чего за ними открывается ожидаемый
profile screen.

В кейсе 7307 проблема двойная: первый dump попал на feed (renav сработал), но
после renav profile вновь был перекрыт другим promo-модалом — re-verify вернул
unknown → `no profile after re-nav`.

## Решение (Variant A — single-shot pre-feed-probe)

Расширить `_tt_handle_post_switch_unknown` двумя точками вызова нового helper'а
`_tt_try_dismiss_post_switch_modal(xml)`:

1. **Pre-feed probe** — после получения `xml_after_pick`, до `_is_tt_feed_after_pick`.
   Если whitelist-модалка совпала → tap dismiss → re-dump → re-verify. По результату:
   - `match` → return `('recovered', current, None)` с событием
     `tt_post_switch_recovered_via_modal_dismiss`.
   - `unknown`/`mismatch` → fall through к existing logic с обновлённым XML.
2. **Post-renav probe** — после `_post_switch_verify_handle(xml_after_renav)`, если
   `status == 'unknown'`. Тот же helper, та же логика. Покрывает 7307.

**Cap = 1 dismiss attempt per probe site** (максимум 2 за весь handle). Никаких
рекурсий, никаких циклов: если после dismiss всё равно unknown — fail с прежним
error_code.

### Псевдокод

```python
def _tt_handle_post_switch_unknown(self, target, xml_after_pick, header_y_max, label, attempt):
    # NEW Step 0a: pre-feed-detect probe
    dismissed_xml = self._try_dismiss_and_redump(xml_after_pick, probe_site='pre_feed',
                                                  target=target, label=label, attempt=attempt)
    if dismissed_xml is not None:
        status, current = self._post_switch_verify_handle(target, dismissed_xml,
                                                          header_y_max=header_y_max)
        if status == 'match':
            self.p.log_event('account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                             meta={'probe_site': 'pre_feed', 'target': target,
                                   'current': current, 'attempt': attempt + 1})
            return ('recovered', current, None)
        # fall through with new XML
        xml_after_pick = dismissed_xml

    # Existing: feed-detect
    is_feed = self._is_tt_feed_after_pick(xml_after_pick, header_y_max)
    if not is_feed:
        return ('failed', None, self._fail(
            f'tt_post_switch_verify_unrecoverable: unknown header non-feed '
            f'(target={target!r})', step=label))

    # Existing: renav
    nav_ok = self._navigate_to_profile_tab()
    if not nav_ok:
        # unchanged
        ...
    xml_after_renav = self.p.dump_ui(retries=1) or ''
    self._save_dump(f'{label}_renav', xml_after_renav)
    status, current = self._post_switch_verify_handle(target, xml_after_renav,
                                                      header_y_max=header_y_max)

    # NEW Step 3a: post-renav probe
    if status == 'unknown':
        dismissed_xml = self._try_dismiss_and_redump(xml_after_renav,
                                                      probe_site='post_renav',
                                                      target=target,
                                                      label=f'{label}_renav',
                                                      attempt=attempt)
        if dismissed_xml is not None:
            status, current = self._post_switch_verify_handle(target, dismissed_xml,
                                                              header_y_max=header_y_max)
            if status == 'match':
                self.p.log_event('account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                                 meta={'probe_site': 'post_renav', 'target': target,
                                       'current': current, 'attempt': attempt + 1})

    if status == 'match':
        # existing renav-recovery event
        ...
    if status == 'mismatch':
        return ('mismatch', current, None)
    return ('failed', None, self._fail(
        f'tt_post_switch_verify_unrecoverable: no profile after re-nav '
        f'(target={target!r})', step=f'{label}_renav'))
```

`_try_dismiss_and_redump(xml, probe_site, target, label, attempt)`:

```python
def _try_dismiss_and_redump(self, xml, *, probe_site, target, label, attempt):
    """Return new XML after dismiss, or None if no whitelist match / tap failed."""
    matched = _tt_try_dismiss_post_switch_modal(xml)
    if matched is None:
        return None
    title_substr, button_text = matched
    self.p.log_event(
        'info', 'tt_post_switch_modal_dismiss_attempted',
        meta={'title_substr': title_substr, 'button_text': button_text,
              'probe_site': probe_site, 'target': target, 'attempt': attempt + 1},
    )
    # Use existing tap_element pattern (publisher_base.py:1600) — substring
    # match + clickable_only. Title-check в helper уже подтвердил, что нужный
    # модал на экране, так что риск ложного тапа по другому "Не сейчас" минимален.
    tapped = self.p.tap_element(xml, [button_text], clickable_only=True)
    if not tapped:
        self.p.log_event(
            'warning', 'tt_post_switch_modal_dismiss_no_recovery',
            meta={'title_substr': title_substr, 'target': target,
                  'probe_site': probe_site, 'reverify_status': 'tap_failed'},
        )
        return None
    time.sleep(1.0)
    new_xml = self.p.dump_ui(retries=1) or ''
    self._save_dump(f'{label}_after_modal_dismiss', new_xml)
    return new_xml
```

## Whitelist (module-level)

```python
# account_switcher.py — рядом с _TT_FEED_MARKERS (line 216)
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # (title_substring, dismiss_button_text)
    # Evidence: WP #67, tasks 6514/6631/6704/6786 (2026-05-15..18)
    ('Привязать номер телефона или эл. почту', 'Не сейчас'),
    # Evidence: WP #67, task 7307 post-renav (2026-05-18)
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

Расширяется по одной строке при появлении новой evidence.

## Алгоритм детекции

`_tt_try_dismiss_post_switch_modal(xml) -> Optional[tuple[str, str]]`:

1. Если `xml` пустой → return None.
2. `elements = parse_ui_dump(xml)`; если пустой → return None.
3. Для каждой `(title_substr, button_text)` пары в whitelist:
   a. Найти любой `el` с `title_substr` в `el.label` (label уже объединяет text + content-desc).
   b. Найти `clickable` `el2` с `el2.label.strip().lower() == button_text.lower()`
      (exact match нижним регистром; `_tt_try_dismiss_post_switch_modal` не делает
      сам tap — он только подтверждает, что нужный модал на экране и что button
      присутствует и кликабелен).
   c. Если оба найдены → Return `(title_substr, button_text)`.
4. Return None.

Order whitelist matters: первое совпадение выигрывает. Кейсы whitelist не пересекаются
(разные title_substr).

**Tap делается caller'ом** через `self.p.tap_element(xml, [button_text],
clickable_only=True)` — существующий паттерн (`account_switcher.py:4013, 4126, 4823`,
реализация `publisher_base.py:1600`). `tap_element` использует substring-match по
`(text + content-desc).lower()`. Title-check в helper'е выше гарантирует, что
нужный модал на экране, а не другой контекст с тем же словом «Не сейчас».

## Телеметрия

Три новых event-категории (через `self.p.log_event`):

| event_name | type | meta | когда |
|---|---|---|---|
| `tt_post_switch_modal_dismiss_attempted` | `info` | `title_substr, button_text, probe_site, target, attempt` | перед tap dismiss |
| `tt_post_switch_recovered_via_modal_dismiss` | `account_switch` | `title_substr, target, current, probe_site, attempt` | re-verify после dismiss = match |
| `tt_post_switch_modal_dismiss_no_recovery` | `warning` | `title_substr, target, probe_site, reverify_status` | re-verify после dismiss = unknown/mismatch |

**Никаких новых `error_code`:** существующие `tt_post_switch_verify_unrecoverable:
unknown header non-feed` / `no profile after re-nav` сохраняются. До/после фикса
различаются по наличию `tt_post_switch_modal_dismiss_attempted` в events до fail'а.

## Тесты

`tests/test_account_switcher.py` (модуль уже существует; следовать существующей конвенции).

### Unit `_tt_try_dismiss_post_switch_modal`

Сохранённые XML-фикстуры в `tests/fixtures/account_switcher/`:
- `wp67_modal_phone_email_6514.xml` (≡ 6631, 6704, 6786 — байт-в-байт).
- `wp67_modal_save_login_7307_renav.xml` (post-renav dump 7307).
- `wp67_profile_5817.xml` (negative — реальный profile screen с `@handle`).
- `wp67_feed_7307_initial.xml` (negative — TT feed top-bar).

Кейсы:
1. `modal_phone_email_6514.xml` → returns `('Привязать номер телефона или эл. почту', 'Не сейчас')`.
2. `modal_save_login_7307_renav.xml` → returns `('Сохранить данные для входа', 'Не сейчас')`.
3. `profile_5817.xml` → returns `None`.
4. `feed_7307_initial.xml` → returns `None`.
5. XML только с title без button → `None`.
6. XML только с button без title → `None`.
7. Пустой XML → `None`.
8. `parse_ui_dump` вернул `[]` → `None`.
9. Button существует, но `clickable=false` → `None`.

### Integration `_tt_handle_post_switch_unknown`

Mock `self.p` (publisher proxy — `log_event`, `dump_ui`, `tap_element`, `adb`) и метод
`_post_switch_verify_handle`. См. memory `reference_publisher_proxy_api` —
вызывать через `self.p.<method>`, не приватные методы publisher'а.

Сценарии:
1. **Pre-feed dismiss happy path:** `xml_after_pick = modal_phone_email`,
   mock `_post_switch_verify_handle` после dismiss → `('match', target)`.
   → return `('recovered', target, None)`. Проверить event
   `tt_post_switch_recovered_via_modal_dismiss` с `probe_site='pre_feed'`.
2. **Post-renav dismiss happy path:** `xml_after_pick = feed`, renav возвращает
   True, `xml_after_renav = modal_save_login`, mock verify после dismiss →
   `('match', target)`. → return `('recovered', target, None)`,
   `probe_site='post_renav'`.
3. **Whitelist miss → existing fail:** `xml_after_pick = unknown_screen`, no
   modal match → existing `is_feed=False` path → return
   `('failed', None, fail_result)` с прежним error_code.
4. **Modal matched, re-verify still unknown:** `xml_after_pick = modal`,
   `_post_switch_verify_handle` после dismiss → `('unknown', None)`.
   → fall through; `_is_tt_feed_after_pick(dismissed_xml)` определяет дальнейший
   путь. Event `tt_post_switch_modal_dismiss_no_recovery` залогирован.
5. **Modal matched, re-verify mismatch:** `xml_after_pick = modal`, после dismiss
   verify = `('mismatch', other_user)`. → fall through; existing logic.

Reference: live-DB engine.dispose fixture **не нужен** — UI-only тесты.

### Pre-deploy verification

Прогон фикса против сохранённых дампов 6514/6631/6704/6786/7307 (полный
`_tt_handle_post_switch_unknown` с реальным `_post_switch_verify_handle` и stubbed
`self.p.tap_element`/`dump_ui`/`adb`):
- 6514/6631/6704/6786: pre-feed probe → match `('Привязать номер...', 'Не сейчас')`
  → re-verify должен вернуть match (мокаем как success).
- 7307: feed branch → renav → post-renav probe → match `('Сохранить данные...', 'Не сейчас')`.

После deploy — live re-queue 2–3 из 5 задач через `publish_queue` reset
(см. memory `reference_publish_requeue_path`).

## Risks & mitigation

| Риск | Mitigation |
|---|---|
| False-positive dismiss (модалка matched, но скрывает важный экран) | Whitelist требует совпадения **и** title_substr, **и** button text — оба должны быть на экране. Whitelist seeded только из observed evidence. |
| TT поменяет тексты в локали | `tt_post_switch_modal_dismiss_attempted` события дают evidence-trail; при mismatch старый fail сохранится и попадёт в триаж. |
| Cap=1 на probe-site недостаточен (3 модалки подряд) | Не наблюдалось; `tt_post_switch_modal_dismiss_no_recovery` события покажут необходимость поднять cap. |
| `tap_element` не нашёл кнопку (DOM сместился между helper-валидацией и tap) | `tap_element` возвращает False → helper логирует `tt_post_switch_modal_dismiss_no_recovery` с `reverify_status='tap_failed'` и возвращает None → existing fail. |
| Регрессия в других call-site `get_current_account_from_profile` | Variant A не трогает 3 другие call-site (initial-read, mismatch-retry, two others). Blast radius — одна функция. |

## Out-of-scope (явно)

- Реклассификация `_is_tt_feed_after_pick` → classifier enum (Variant C из брейншторма).
- Generic pre-verify dismiss во всех 4 call-site `get_current_account_from_profile`
  (Variant B): отсутствие evidence по этим путям; добавим при появлении.
- Расширение whitelist на IG/YT modals — отдельные WP по своим багам.
- Изменения `_TT_FEED_MARKERS`: текущий список покрывает feed (задача 7307 шла
  через feed-ветку успешно).
- Изменения `_post_switch_verify_handle` или `get_current_account_from_profile`
  (Layer 1 уже shipped; этот фикс работает поверх).

## Deploy & rollback

- Deploy через PM2 ecosystem restart (memory `feedback_deploy_scope_constraints`),
  prod path `/root/.openclaw/workspace-genri/autowarm` (auto-push hook —
  `reference_autowarm_git_hook`).
- Rollback: revert PR; `_TT_POST_SWITCH_DISMISSIBLE_MODALS = ()` (пустой кортеж)
  — helper всегда вернёт None, поведение идентично pre-fix.
- Kill-switch не требуется: код trivially-defeatable пустым whitelist'ом
  без env-var (memory `feedback_deploy_scope_constraints` — SQL/code-level
  flags для PM2 services).

## 24h soak

После выката следить `failmsg LIKE '%tt_post_switch_verify_unrecoverable%'`
24ч:
- Expected: 1–2/день → ~0.
- Trigger для дополнительной итерации: ≥1 fail с новым modal title в логах
  `tt_post_switch_modal_dismiss_attempted`-attempts = 0 (т.е. whitelist
  не покрыл) → завести event evidence и расширить whitelist.

Query:
```sql
WITH last_fail AS (
  SELECT pt.id, pt.created_at,
         (SELECT e->>'msg' FROM jsonb_array_elements(pt.events) WITH ORDINALITY x(e,ord)
          WHERE e->>'type'='fail' ORDER BY ord DESC LIMIT 1) AS failmsg,
         (SELECT count(*) FROM jsonb_array_elements(pt.events) e
          WHERE e->>'msg' LIKE 'tt_post_switch_modal_dismiss_attempted%') AS modal_attempts
  FROM publish_tasks pt
  WHERE pt.platform='TikTok' AND pt.status='failed' AND pt.testbench=false
    AND pt.created_at >= NOW() - INTERVAL '24 hours'
)
SELECT count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%') AS verify_fails,
       count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%' AND modal_attempts = 0) AS verify_fails_no_dismiss
FROM last_fail;
```
