# WP #181 — IG `ig_share_tap_no_progress` — post-mortem success probe

**Дата:** 2026-05-28
**OpenProject:** #181
**Связано:** WP #73 (исходный фикс детекта успеха через `InstagramMainActivity`), WP #105 (stale uiautomator на IG-launch), WP #131 (stale UI на TT-профиле)

## Контекст и evidence

Триаж IG-падений 22.05–28.05: после стабилизации watchdog (WP #165) топ-1 устойчивая IG-ошибка — `ig_share_tap_no_progress` (99 за 7д, 27.05=45, 28.05=12 за неполный день).

Первичная гипотеза: новый pre-Share экран «Добавить значок ИИ» блокирует Share-tap. Гипотеза **опровергнута** при детальном разборе UI-дампа (`task 11660 → wait_upload_iter0`): «Добавить значок ИИ» — обычная inline-опция Reels editor, рядом с «Отметить людей» / «Добавить место» / «Переименовать аудио». Toggle `[889,1728][1035,1863]` checkable+clickable, по умолчанию **выключен** (серый), Share-кнопка `share_button` остаётся активной и не блокируется.

**Реальная причина** (подтверждено разбором кадров скринкастов 3/3 свежих fail):

| task | финал скринкаста | пост опубликован? |
|------|------------------|--------------------|
| 11660 | Reels feed (`maksim_expertestate`, текст про недвижимость = наш caption) | **ДА** |
| 11472 | Reels feed (`azure_dubai_estates`, текст «From waterfront residences…» совпадает с caption) | **ДА** |
| 11646 | Reels feed (`smartestatespb`, наш аккаунт) | **ДА** |
| 11459 | Search-экран | другой сценарий |

Минимум 3/3 проверенных — **false-negative**: пост опубликован, но автоматизация регистрирует fail.

### Механика false-negative

1. Share-tap проходит, IG начинает публикацию.
2. Transit `com.instagram.modal.ModalActivity` → Reels feed activity занимает **>30s** (probe deadline в `_wait_instagram_upload`).
3. На момент `wait_upload_iter0_diag` (~5s после Share) и в течение pre-Tier1 probe (30s, 6 итераций × 6s) `dumpsys activity` показывает всё ещё `ModalActivity` (transit не закончен).
4. После probe `_is_ig_editor_still_visible(self.dump_ui())` возвращает `True` — но **UI dump stale** (рецидив паттерна WP #131 для IG): real activity уже Reels feed, а uiautomator всё ещё отдаёт старый editor XML.
5. Tier 1 retry × 2 (`ig_share_retry`) + Tier 1.5 (`action_bar_OK fallback tap`) → всё мимо реального экрана.
6. Final: `ig_share_tap_no_progress` пишется в `publish_tasks.error_code`. Пост уже опубликован, но `url_capture_attempts=0`, post_url пуст, задача помечена `failed`.

### Связь с WP #73

WP #73 решал ту же проблему ложно-негативного fail-detection через расширение `SUCCESS_ACT_TOKENS` именем `InstagramMainActivity` под флагом `IG_MAIN_ACTIVITY_SUCCESS_ENABLED`. Текущий рецидив — продолжение того же класса багов, но:
- transit может занимать дольше probe deadline (30s);
- наблюдаемое post-publish activity может быть **другим** именем, не покрытым существующим `SUCCESS_ACT_TOKENS = (MainTabActivity, ReelViewerActivity, IgFeedActivity, +InstagramMainActivity)`.

## Цель

Перестать классифицировать опубликованные посты как failed: финальный пост-mortem success probe **на этапе fail**, before mark `share_no_progress = True`.

## Не-цели (Phase 1)

- Не пытаемся handle-ить какие-либо новые модалы / overlay.
- Не меняем pre-Tier1 probe (он работает корректно, просто иногда transit длиннее его deadline).
- Не трогаем `_is_ig_editor_still_visible` (его stale-issue эффективно обходится через probe-based ground truth).
- Не ставим `account_blocks` — false-negative не специфика аккаунта.
- Не вводим новый error_code (`ig_ai_label_required` из первой версии дизайна не нужен — экран не блокирующий).

## Архитектура

### Точка вставки

`publisher_instagram.py:_wait_instagram_upload` (L2994–3153), внутри `if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):` ветки (L3136), **перед** установкой `share_no_progress = True` (L3148).

### Логика post-mortem probe

```
# Псевдокод
если final fail условие выполнено:
  если kill-switch IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED == true:
    дать transition ещё ~POSTMORTEM_GRACE_S секунд (e.g. 20s):
      poll dumpsys activity каждые 5s
      если activity ∈ SUCCESS_ACT_TOKENS_EXTENDED → break, success
    если transition подтверждён:
      log_event(info, 'Instagram: share post-mortem transit confirmed',
                meta={'category': 'ig_share_postmortem_success',
                      'topResumedActivity': <act>,
                      'reclassified_from': 'ig_share_tap_no_progress'})
      return True   # uplift в основной wait_upload loop, который ловит post_url
                    # (или, если основной loop тоже timeout — задача уйдёт в awaiting_url
                    # и url-poller выкатит url, WP#86 PR1 механика)
    иначе:
      старое поведение: log ig_share_tap_no_progress, return False
  иначе (kill-switch off):
    старое поведение
```

### Логика probe: одна стратегия, без whitelist

Вместо расширения именованного whitelist (хрупко — каждый новый билд IG может ввести новое имя) используем **отрицательную сигнатуру**: progress подтверждён ⇔ IG-package в foreground **и** activity покинула `ModalActivity` (= editor закрыт).

```python
def _is_ig_post_share_progressed(act_line: str) -> bool:
    """True, если IG-package остаётся в foreground, но editor (ModalActivity) покинут."""
    if 'com.instagram.android' not in act_line:
        return False
    if 'ModalActivity' in act_line:
        return False
    return True
```

Помимо decision-логики, мы **записываем фактическое имя activity** в meta события `ig_share_postmortem_success` (для аналитики покрытия). Это даёт ground-truth список activity-имён без жёсткой зависимости от него в коде.

### Возвращаемое значение

**Одна стратегия, без условных веток:** если post-mortem probe подтвердил progress:
1. **НЕ пишем** event `ig_share_tap_no_progress` (existing error event на L3137-3143);
2. **Пишем** info-event `ig_share_postmortem_success` с `meta.topResumedActivity = <observed>` и `meta.grace_elapsed_s = <seconds>`;
3. `share_no_progress = False`, **fall-through в основной success-loop** (L3155+) — он либо ловит `SUCCESS_KW` / `post_url`, либо встаёт в `awaiting_url`.

В обоих исходах url-poller (WP #86 PR1, уже в проде) подберёт URL в течение ~5 минут и закроет задачу как `published` / `exhausted_awaiting_url`. Главное — **уходит флажок `failed` с кодом `ig_share_tap_no_progress`**.

Если probe **не подтвердил** progress (transit реально не произошёл) — старое поведение в точности сохраняется.

### Kill-switch

`IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED` (default `true`).
- `true` → новое поведение (post-mortem probe + переклассификация);
- `false` → старое поведение (мгновенный fail после Tier 1 + 1.5).

Параметры probe — также через env:
- `IG_SHARE_POSTMORTEM_GRACE_S` (default 20)
- `IG_SHARE_POSTMORTEM_POLL_S` (default 5)

## Компоненты

1. **`_is_ig_post_share_progressed(act_line: str) -> bool`** — pure helper, чистая логика. Тестируется unit-тестами.
2. **Block в `_wait_instagram_upload`** — оркестрация probe, использует существующие `self.adb()` и `self.log_event()`.
3. **Env-переменные** — чтение через `os.environ.get(...)` в самом блоке (как уже сделано для `IG_MAIN_ACTIVITY_SUCCESS_ENABLED`).

## Тестирование

### Unit
- `_is_ig_post_share_progressed("topResumedActivity=…/InstagramMainActivity")` → `True`
- `_is_ig_post_share_progressed("topResumedActivity=…/ReelViewerActivity")` → `True`
- `_is_ig_post_share_progressed("topResumedActivity=…/com.instagram.modal.ModalActivity")` → `False`
- `_is_ig_post_share_progressed("topResumedActivity=…/com.android.launcher")` → `False` (не IG)
- `_is_ig_post_share_progressed("")` → `False`

### Integration / mock-publisher
- mock ADB: probe возвращает Reels-activity на iteration 2 → `_wait_instagram_upload` НЕ пишет `ig_share_tap_no_progress`, пишет `ig_share_postmortem_success`, возвращает `False` (или `True` если основной loop ловит SUCCESS_KW).
- mock ADB: probe возвращает `ModalActivity` все iterations → старое поведение: `ig_share_tap_no_progress`.
- `IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED=false` + probe вернёт Reels-activity → старое поведение `ig_share_tap_no_progress` (флаг работает).

### Regression
- Полный набор существующих тестов в `tests/test_publisher_instagram*.py` — без регрессий.

### Post-deploy verification (24h)
- Метрика: дневной счётчик `ig_share_tap_no_progress` в `publish_tasks` за 7д до vs 7д после.
- Метрика: счётчик `ig_share_postmortem_success` (новый info-event).
- Sanity: 5 случайных задач с `ig_share_postmortem_success` — проверка реального наличия поста в IG-аккаунте.

## Деплой

1. PR в `~/autowarm-testbench` (отдельная ветка `feat/wp181-ig-share-postmortem-probe`).
2. Tests green локально (live PG через autouse fixture / pytest).
3. `codex review` round до 0 P1 (memory practice).
4. Merge → автодеплой autowarm через post-commit git-hook (если применимо) **или** ручная синхронизация autowarm-testbench на VPS + `pm2 restart autowarm-*` (по стилю проекта).
5. Включить kill-switch на проде (default true — уже включён, дополнительных действий не требуется).

## Риск-анализ

| Риск | Митигация |
|---|---|
| Post-mortem probe удлиняет fail-path на 20s | Только для задач, которые уже в шаге fail (99/неделя). Доп. время не критично; защищает 99 false-negatives. |
| Whitelist activity имен неполный | `_is_ig_post_share_progressed` fail-safe: всё, что не `ModalActivity` + в IG-package → progress. |
| False-positive postmortem success | Конкретный кейс: пользователь сам ушёл из editor через BACK без публикации. Маловероятно (это автомат, не ручной flow). Митигация: pad post_url polling через url-poller (если URL не схвачен через 30 мин → задача переходит в exhausted_awaiting_url, WP #86). |
| Транзит дольше 20s grace | Поднять `IG_SHARE_POSTMORTEM_GRACE_S` до 30-40s. Параметр через env. |

## Открытые вопросы

- Точные имена post-publish activity на текущем билде IG (для расширения SUCCESS_ACT_TOKENS) — собираются в Step 1 плана через адхок-замер `dumpsys` на тестбенче и парс существующих success-задач.
- 11459 ушёл в Search вместо Reels feed — отдельный сценарий, возможно реальный fail. Анализ — отдельной задачей (не блокер этого WP).

## Откат

`IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED=false` в `.env` autowarm + `pm2 restart` или `pkill` цикла. Старое поведение возвращается мгновенно, без миграций / данных.
