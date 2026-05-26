# WP #156 — TT retry tt_3_open_list: честный tt_fg_drift_unrecoverable вместо generic

**Дата:** 2026-05-26
**Репозиторий правки:** `GenGo2/delivery-contenthunter` (autowarm), файл `account_switcher.py`
**Тип:** observability / honesty-фикс (не новый recovery)
**Kill-switch:** `TT_SWITCH_FG_GUARD_ENABLED` (существующий, default ON)

## Проблема

При переключении аккаунта в TikTok бот на ретрае иногда теряет передний план
(сворачивается в лаунчер / уходит в Instagram / перезапускается). На **первичном**
пути после WP #130 (PR #97, прод `486fec2`) эта ситуация эмитит честный код
`tt_fg_drift_unrecoverable`. А на **ретрае** (`_switch_tiktok`, ветка
`tt_3_open_list_retry_{attempt}`, прямой тап через `_tap_profile_header` минуя
`_open_tt_account_switcher` и его fg-guard) потеря переднего плана падает в общий
`publish_failed_generic`. Реальный foreground-drift на ретраях прячется в
generic-корзине → триаж видит ложную долю.

## Корень (подтверждён по живому коду)

`_switch_tiktok` содержит цикл `for attempt in range(MAX_PICK_ATTEMPTS)`. На
ретрае (`attempt > 0`) после cold-restart и `_go_to_profile_tab` список аккаунтов
открывается **своим** прямым тапом `_tap_profile_header`, в обход первичного
fg-guard'а. Два `_fail`-сайта возвращают generic:

- `account_switcher.py:3156-3159` — `'header tap failed после TT post-switch retry'`
  (после `_tap_profile_header(...) → False`);
- `account_switcher.py:3166-3170` — `'bottomsheet не открылся после TT post-switch retry'`
  (когда `anchor_bounds_retry` пуст).

Оба со `step=f'tt_3_open_list_retry_{attempt}'`. Этот step **отсутствует** в
`_SWITCHER_STEP_TO_CATEGORY` (`publisher_kernel.py`) → publisher резолвит его в
`publish_failed_generic`.

Первичный путь, напротив, при drift эмитит честно (`account_switcher.py:4606-4611`,
helper `_tt_guard_switcher_foreground` + drift-during-probe re-check), и
`_SWITCHER_STEP_TO_CATEGORY['tt_fg_drift_unrecoverable'] = 'tt_fg_drift_unrecoverable'`
(`publisher_kernel.py:105`) гарантирует честную категорию даже при потере
error-события (Pass-2 fallback).

## Доказательная база

Из re-триажа WP #96 (`docs/evidence/2026-05-26-wp96-tt-bottomsheet-not-reproducing.md`):
сегодня (26.05) 4 TT-задачи в `publish_failed_generic` — 9832 / 9767 / 9742 / 9713.
У всех bottomsheet открылся штатно, реальная причина — `tt_post_switch_mismatch`
+ `switcher_foreground_pkg_disagree` (foreground-drift), финальный fail на шаге
`tt_3_open_list_retry_1` / `tt_4_target_profile_retry_1`.

## Решение (Подход A — реактивная проверка в точках падения)

Зеркалируем инструментовку первичного пути на retry-ветку **реактивно**: в двух
существующих `_fail`-сайтах, *перед* возвратом generic, проверяем foreground.
Если ушли с `cfg['package']` (== `com.zhiliaoapp.musically`) → эмитим честный
`tt_fg_drift_unrecoverable` с `foreground_pkg` + `probe_top_labels` и
`_fail(step='tt_fg_drift_unrecoverable')`. Иначе — generic как раньше. Всё под
существующим kill-switch `TT_SWITCH_FG_GUARD_ENABLED`.

**Почему реактивно, а не проактивный guard в начале ретрая:** проверка foreground
выполняется только когда мы уже падаем → ноль лишних ADB-дампов на happy-path,
успешный путь не трогается вообще. Drift по evidence проявляется *в процессе*
навигации, поэтому проактивная проверка до тапа всё равно не покрыла бы часть
кейсов и реактивная нужна в любом случае.

**Почему без recovery:** бриф явно — это observability/honesty-фикс. Восстановление
при drift на ретрае (relaunch + re-navigate, как делает `_tt_guard_switcher_foreground`
на первичке) оставлено на отдельный вопрос. Здесь только честная классификация.

### Новый helper

```python
def _tt_retry_fg_drift_or_none(self, target, cfg, step, probe_elements=None):
    """[WP #156] На retry-ветке tt_3_open_list: если foreground ушёл с TikTok —
    эмитим честный tt_fg_drift_unrecoverable вместо generic и возвращаем
    SwitchResult (caller обязан его вернуть). Иначе None. Observability-only,
    БЕЗ recovery (см. WP #156). Гейт — TT_SWITCH_FG_GUARD_ENABLED."""
    if not _tt_switch_fg_guard_enabled():
        return None
    fg_pkg = self._detect_foreground_pkg()
    if not fg_pkg or fg_pkg == cfg['package']:
        return None
    self.p.log_event(
        'error',
        f'tt_fg_drift_unrecoverable (retry): foreground={fg_pkg!r} на {step}',
        meta={'category': 'tt_fg_drift_unrecoverable',
              'reason': 'tt_account_switcher_wrong_foreground',
              'foreground_pkg': fg_pkg,
              'target': target,
              'step': step,
              'platform': 'TikTok',
              'probe_top_labels': _top_labels(probe_elements or [], 30)})
    return self._fail(
        'TikTok не на переднем плане на retry-ветке открытия панели аккаунтов '
        '(foreground drift)',
        step='tt_fg_drift_unrecoverable')
```

### Вызовы в retry-ветке `_switch_tiktok`

```python
# ~3152: после _tap_profile_header → False
if not self._tap_profile_header(...):
    drift = self._tt_retry_fg_drift_or_none(
        target, cfg, f'tt_3_open_list_retry_{attempt}')
    if drift is not None:
        return drift
    return self._fail('header tap failed после TT post-switch retry',
                      step=f'tt_3_open_list_retry_{attempt}')

# ~3166: anchor_bounds_retry пуст
if not anchor_bounds_retry:
    drift = self._tt_retry_fg_drift_or_none(
        target, cfg, f'tt_3_open_list_retry_{attempt}',
        probe_elements=post_elements_retry)
    if drift is not None:
        return drift
    return self._fail('bottomsheet не открылся после TT post-switch retry',
                      step=f'tt_3_open_list_retry_{attempt}')
```

## Ключевые инварианты

- **Разделение step'ов:** `meta['step']` хранит `tt_3_open_list_retry_{attempt}`
  (триаж отличает retry-drift от первичного), а `_fail`'s `final_step =
  'tt_fg_drift_unrecoverable'` даёт честную категорию через
  `_SWITCHER_STEP_TO_CATEGORY`. Точное зеркало первичного пути.
- **Happy-path не меняется:** helper вызывается только в уже-падающих ветках;
  при `fg == cfg['package']` или kill-switch OFF возвращает `None` → старое
  generic-поведение сохраняется.
- **`probe_top_labels`:** на bottomsheet-сайте используется уже распарсенный
  `post_elements_retry`; на header-tap-сайте распарсенного дампа нет, передаём
  `None` → `_top_labels([], 30) == []` (пустой список, без лишнего dump_ui).
- **Без нового recovery:** ни relaunch, ни re-navigate на ретрае.

## Тестирование

Unit-тесты на helper с fake-proxy (по образцу тестов WP #130):

1. **foreign pkg + guard ON** → результат `SwitchResult` с
   `final_step == 'tt_fg_drift_unrecoverable'` и `success == False`; залогировано
   error-событие с `meta.category == 'tt_fg_drift_unrecoverable'`,
   `meta.foreground_pkg`, `meta.step == 'tt_3_open_list_retry_1'`.
2. **kill-switch OFF** (`TT_SWITCH_FG_GUARD_ENABLED=0`) → `None` (generic-путь
   сохраняется).
3. **fg == TikTok** (`cfg['package']`) → `None`.
4. (структурный) оба `_fail`-сайта retry-ветки вызывают
   `_tt_retry_fg_drift_or_none` перед generic-`_fail`.

Fake-proxy должен предоставлять `_detect_foreground_pkg`, `log_event`, и поля,
нужные `_fail`/`SwitchResult` (`_attempts`, `_screenshots`, `_dumps`). Сверять
имена методов 1-в-1 с `DevicePublisher` (риск mock-proxy drift).

## Деплой

- Правка одного python-файла `account_switcher.py` — per-task spawn подхватит без
  pm2 restart (как WP #112/#130/#106).
- Разработка и тесты — в **git-worktree** autowarm-репозитория, НЕ чекаутить
  feature-ветку в прод-дире `/root/.openclaw/workspace-genri/autowarm/` (там
  живой код PM2; чекаут ветки подменит прод).
- PR в `GenGo2/delivery-contenthunter` → codex review → merge → в прод-дире
  `git pull` на `main` для выкладки.
- Kill-switch `TT_SWITCH_FG_GUARD_ENABLED=0` откатывает и первичный, и retry-путь
  к legacy-поведению (общий рубильник — намеренно, drift-инструментовка едина).

## Не в скоупе

- Recovery (relaunch/re-navigate) при drift на ретрае — отдельный вопрос.
- Ветка `tt_4_target_profile_retry_*` (post-switch verify mismatch) — там уже
  honest-категория `tt_post_switch_mismatch`, не generic.
- Изменение поведения первичного пути.
