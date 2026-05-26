# WP #160 — TikTok: модалка разлогина «Вы вышли из аккаунта» не распознаётся

**Дата:** 2026-05-26
**Parent:** WP #131 (`tt_profile_tab_broken`, stale-UI guard) — выделено как out-of-scope long-tail child разведкой 2026-05-26.
**Тип:** Ошибка (категория A — чёткая спека, низкий риск, scoped).
**Целевой код:** прод autowarm `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (+ `publisher_kernel.py`). PR — в `GenGo2/delivery-contenthunter`. Доки — в `rmbrmv/contenthunter`.

## Проблема

TikTok при разлогине показывает модальный диалог «Статус аккаунта»:

- title: `text="Статус аккаунта"` — non-clickable `TextView`;
- body: `text="Вы вышли из аккаунта. Попробуйте войти снова."` — non-clickable `TextView` (`android:id/message`);
- кнопка: `text="OK"` — clickable `Button` (`android:id/button1`).

Это **не** стандартный экран логина: кнопок «Войти»/«Создать аккаунт»/social-login row нет, поэтому существующий детектор `_tt_is_logged_out` (маркеры `_TT_LOGGED_OUT_MARKERS`) её не ловит. Модалка sticky висит поверх профиля. Own-profile петля верификации (`account_switcher.py:2804-2974`) прогоняет 3 retap'а (обычный tap → smart_tap → force-stop+relaunch), все 4 детектора (own/logged_out/reauth/foreign) дают False, петля исчерпывается и падает общей ошибкой `tt_profile_tab_broken` (`tt_2_not_own_profile`).

**Эффект:** зря сжигаются попытки + cold-start, а триаж получает бесполезный `tt_profile_tab_broken` вместо честной причины «аккаунт разлогинен, нужен ручной вход».

## Доказательства

Задача **9652** (аккаунт `LexisVoice_Up`, устройство `RFGYB180RZV`, 25.05.2026, `status=failed`, `error_code=tt_profile_tab_broken`).

Последовательность категорий событий: `… tt_bound_nav ×4 → tt_profile_tab_broken`. Дампы own-profile retap'ов (`tt_2_not_own_retap1/2/3`) и финальный `fail_tt_2_not_own_profile` **идентичны** (6269 байт) — модалка стоит неизменной все 3 retap'а. В каждом присутствуют ровно три узла модалки (title/body/OK) с флагами выше; никаких login-маркеров. Дамп сохранён в фикстуру.

## Цель / не-цель

**Цель:** распознавать эту модалку отдельным детектором в own-profile петле, помечать аккаунт как требующий ручного входа (`account_blocks`), не сжигать retap'ы, отдавать честный error_code.

**Не-цель (по согласованию с Данилом 2026-05-26):**
- Полноэкранный логин (`_tt_is_logged_out`) **не трогаем** — он уже валит честным кодом; добавление туда `account_blocks`-заморозки расширило бы scope (при желании — отдельный мелкий WP).
- Кнопку «OK» **не тапаем** (см. ниже).
- Гейтинг publish-очереди по `account_blocks` вне scope: `tt_block` исключает аккаунт из фарминг/warming-ротации (`farming_orchestrator`/`testbench_orchestrator`), но не из publish-очереди — как и у WP #93. Это сознательно.

## Дизайн (Approach A — выделенный детектор по образцу WP #93)

Отвергнутые альтернативы: **B** (расширить маркеры `_tt_is_logged_out` + заморозка в его ветку) — объединил бы модалку с полным экраном под одним error_code и потащил заморозку в полноэкранную ветку (против согласованного scope). **C** (переиспользовать whitelist `_TT_SWITCH_BLOCKING_MODALS` + его handler) — тот handler хардкодит `step=tt_switch_blocked`/`last_seen_screen=tt_4_target_profile`/текст эскалации под switch-флоу → телеметрия соврёт для own-profile падения.

### 1. Детект

Новый module-level whitelist рядом с `_TT_SWITCH_BLOCKING_MODALS`:

```python
_TT_LOGGED_OUT_MODALS: tuple[tuple[str, str, str], ...] = (
    ('Вы вышли из аккаунта', 'OK', 'manual_login_required'),
)
```

Тело матча выносится из `_tt_detect_switch_blocking_modal` в общий helper `_tt_match_modal_whitelist(xml, whitelist)`. `_tt_detect_switch_blocking_modal` начинает делегировать ему (whitelist=`_TT_SWITCH_BLOCKING_MODALS`) — поведение WP #93 остаётся byte-identical. Добавляется `_tt_detect_logged_out_modal(xml)`, передающий `_TT_LOGGED_OUT_MODALS`.

Правило матча (неизменно, как WP #93): существует **non-clickable** элемент, чей `label.lower()` содержит `heading_substr.lower()` (heading), **и** существует **clickable** элемент с `label.strip().lower() == button.lower()` (кнопка). Оба в одном дампе. Heading-substring `Вы вышли из аккаунта` уникален; требование точной кнопки «OK» — дополнительная страховка от ложных срабатываний. Defensive: `parse_ui_dump` обёрнут в try/except → на любое исключение `None` (продолжаем на старый verify-флоу).

### 2. Handler

`_maybe_handle_logged_out_modal(self, xml, target, retap)` — зеркало `_maybe_handle_switch_blocking_modal`:

1. kill-switch: если `os.environ.get('TT_LOGGED_OUT_MODAL_GUARD', '1') == '0'` → `return None`;
2. `_tt_detect_logged_out_modal(xml)` в try/except → `None` → `return None` (петля продолжается);
3. при матче:
   - `log.error(...)`;
   - `self.p.log_event('error', 'TT logged-out modal: …', meta={'category':'tt_logged_out_modal', 'reason':'manual_login_required', 'heading_substr':…, 'button_substr':'OK', 'target':target, 'retap':retap+1, 'step':'tt_2_logged_out_modal'})` — эмитится первым (аудит-трейл при сбое downstream);
   - best-effort `account_blocks.set_block_by_username(target, 'tt', reason='manual_login_required', publish_task_id=self.p.task_id, step='tt_2_logged_out_modal', last_seen_screen='tt_2_profile_tab', heading_substr=…)`;
   - best-effort `notifier.notify_escalation('tt_logged_out_modal', …, …)`;
   - `self._save_dump(f'tt_2_logged_out_modal_retap{retap+1}', xml)`;
   - `return self._fail('TikTok разлогинен (модалка «Вы вышли из аккаунта») — нужен ручной вход для @{target}', step='tt_2_logged_out_modal')`.

Каждая внешняя зависимость (`account_blocks`, `notifier`) — в своём try/except (best-effort isolation). Кнопку «OK» **не тапаем**: аккаунт всё равно замораживается, лишний tap = лишний риск (паттерн WP #93 — fail-fast без действия по кнопке).

### 3. Точка вставки

В own-profile петле (`account_switcher.py`), сразу после блока `_tt_is_logged_out` (полный экран) и перед `_tt_is_reauth_prompt`:

```python
_lo = self._maybe_handle_logged_out_modal(xml_probe, target, retap)
if _lo is not None:
    return _lo
```

Срабатывает на первом же retap → не сжигаются 3 retap'а + bottomsheet-recovery. С WP #131 stale-UI гардом не конфликтует: модалка — реальный (не протухший) дамп TikTok, `_tt_probe_looks_stale` по ней False, гард ниже по петле не доходит. Порядок относительно `_tt_is_logged_out` не важен — маркеры непересекающиеся.

### 4. Телеметрия

- Новый `category='tt_logged_out_modal'` (`type='error'`).
- Новая строка в `_SWITCHER_STEP_TO_CATEGORY` (`publisher_kernel.py`): `'tt_2_logged_out_modal': 'tt_logged_out_modal'` (identity-маппинг, как `tt_switch_blocked`).

### 5. account_blocks

`factory_reg_accounts.tt_block` JSONB: `{reason:'manual_login_required', detected_at, publish_task_id, step:'tt_2_logged_out_modal', last_seen_screen:'tt_2_profile_tab', heading_substr, username}`. Новый `reason` (не реюзаем `phone_or_email_link_required` — иная семантика). Существующий API `set_block_by_username` без изменений. Разблокировка — ручной SQL после ручного входа в TikTok.

### 6. Kill-switch / откат

Env `TT_LOGGED_OUT_MODAL_GUARD=0` → handler сразу `None`, флоу идентичен pre-fix (по образцу `TT_STALE_UI_OWN_PROFILE_GUARD` у WP #131). Кодовый фолбэк — пустой whitelist `_TT_LOGGED_OUT_MODALS = ()` → детектор всегда `None`.

## Тестирование

- Фикстура: дамп задачи 9652 → `tests/fixtures/tt_logged_out_modal_9652.xml`.
- Unit (`tests/test_tt_logged_out_modal.py`):
  - детектор матчит фикстуру → `('Вы вышли из аккаунта', 'OK', 'manual_login_required')`;
  - `None` на нормальном own-profile дампе и на feed-дампе (нет ложных срабатываний);
  - `None` на WP #93 phone/email-модалке (нет кросс-матча между whitelist'ами);
  - `None` при heading без кнопки «OK» (синтетический дамп — проверка требования кнопки);
  - kill-switch `TT_LOGGED_OUT_MODAL_GUARD=0` → handler `None`;
  - `_tt_detect_switch_blocking_modal` после рефакторинга матчит свою WP #93 фикстуру byte-identical (регресс delegation).
- Регресс: весь switcher-сьют (`test_account_switcher*`, `test_tt_switch_blocking_modal`, `test_canonical_error_codes`, `test_error_code_mapper`) зелёный.

## Деплой

Код — PR в `GenGo2/delivery-contenthunter`; прод тянет `git pull` в `/root/.openclaw/workspace-genri/autowarm/`, Python спавнится свежим per-task → **PM2 restart не нужен**. Доки (этот spec + plan + evidence) — `rmbrmv/contenthunter`. Работа в git worktree (изоляция от параллельных сессий).

## Acceptance / verify (~24ч после деплоя)

- `count(error_code='tt_logged_out_modal' AND created_at >= NOW() - 24h)` ≥ 0 — категория появилась, падения этой природы больше не маскируются под `tt_profile_tab_broken`.
- Аккаунты с модалкой получают `tt_block.reason='manual_login_required'` и исключаются из warming-ротации.
- `tt_profile_tab_broken` не растёт (модалочная доля ушла в честный код).
