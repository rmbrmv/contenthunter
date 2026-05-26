# WP #159 — TT viewer-history modal dismiss — SHIPPED+DEPLOYED 2026-05-26

**Статус:** SHIPPED+DEPLOYED, OpenProject #159 → «Тестирование».
**Родитель:** WP #131 (child вместе с #160).

## Что было

TikTok-свитч на профиль-табе падал `tt_profile_tab_broken`, когда поверх профиля
всплывала consent-шторка «История просмотров включена» (тоггл ВКЛ + единственная
кнопка «Сохранить», без кнопки отказа). Бот не распознавал свой профиль под шторкой,
исчерпывал 3 retap'а → `_fail(tt_2_not_own_profile)`.

**Воспроизведение:** task 9648, аккаунт komilfo_vibe, устройство RF8Y80ZV1WF, 25.05.
Длиннохвостый кейс (1 из 5 свежих падений), не блокер.

UI-дамп (профиль-таб, task 9648):
`https://save.gengo.io/autowarm/ui_dumps/tiktok/task9648_switch_9648_tt_2_profile_tab_1779701395.xml`

## Что сделано

Аддитивная правка по отлаженному паттерну WP #106 / WP #67 Layer 2 — одна запись в
вайтлист `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS`:

```python
('История просмотров', 'Сохранить'),  # [WP #159] task 9648 — viewer-history consent
```

Детектор `_tt_try_dismiss_profile_promo` требует ОБА: подстроку заголовка
«История просмотров» И clickable-кнопку «Сохранить» → ложноположительные на чистом
профиле исключены. Метод `_tt_dismiss_profile_promo_dialog` (вызывается в retap-петле
`_switch_tiktok` между security-prompt и own-profile-check) тапает кнопку по тексту
(device-agnostic), caller re-dump'ит UI и доходит до own-profile. Новой логики /
error_code / схемы нет. Kill-switch `TT_PROFILE_PROMO_DISMISS_DISABLED=1` — существующий.

**Решение по «Сохранить» (осознанный trade-off, согласован с владельцем 2026-05-26):**
у шторки нет кнопки отказа; единственная текстовая кнопка — «Сохранить», тоггл
«История просмотров» ВКЛ по умолчанию. Закрытие тапом «Сохранить» подтверждает
настройку (история просмотров включается). Для рабочих/бот-аккаунтов несущественно.
Альтернативы (крестик по координатам / выкл-тоггл-then-save / system BACK) отклонены
как device-fragile или рискующие увести с профиль-таба. codex review поднял это как
P2 — известный принятый trade-off, не дефект.

## Тесты

`tests/test_account_switcher_profile_promo_dismiss.py` + фикстур
`tests/fixtures/tt_profile_promo_viewer_history_9648.xml` (реальный дамп task 9648):
- детектор → `('История просмотров', 'Сохранить')`;
- метод → событие `tt_profile_promo_dismiss_attempted` (meta) + tap `['Сохранить']` → True;
- seed-ассерт наличия записи;
- интеграция через `_switch_tiktok`: retap1 viewer-history → dismiss → own-profile →
  break (success, `_fail` не вызван). Тест не-тавтологичен (упал бы без записи вайтлиста).

Прогон: 17/17 в promo-файле; 231 passed по смежным switcher-тестам; 40 passed
(promo + yt-premium-promo) регресс. **6 IG-фейлов в `test_account_switcher.py`
(`test_ig_post_switch_*`, `test_ig_human_check_*`, `test_ig_sa_mode_*`) —
PRE-EXISTING (падают и на проде main без моей ветки), не регрессия WP #159, вне scope.**

## Ревью

- Спек + план: `codex review` clean (0 P1).
- Subagent-driven: по 2 ревью на задачу (spec compliance + code quality), оба Approve.
- Финальный `codex review` на полный дифф ветки: 1×P2 (viewer-history toggle — принятый
  trade-off, см. выше), 0×P1.

## Деплой

- Код: `GenGo2/delivery-contenthunter` main — merge `a675b2d` (--no-ff, мои коммиты
  `1e28825..1a1ee3c`), post-commit hook авто-запушил в прод. Python per-task spawn —
  PM2 restart не нужен. Worktree + feature-ветка (локальная и remote) удалены.
- Прод-путь: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py:376`.

## Остаток (verify ~27.05)

- События `tt_profile_promo_dismiss_attempted` с `title_substr='История просмотров'`
  в логах TT-свитчей → закрытие срабатывает в проде.
- viewer-history-bucket уходит из `tt_profile_tab_broken`.
- При подтверждении → #159 «Готово». Откат при регрессии:
  `TT_PROFILE_PROMO_DISMISS_DISABLED=1`.

Spec: `docs/superpowers/specs/2026-05-26-wp159-tt-viewer-history-modal-dismiss-design.md`
Plan: `docs/superpowers/plans/2026-05-26-wp159-tt-viewer-history-modal-dismiss.md`
