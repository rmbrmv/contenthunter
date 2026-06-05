# OP#255 — IG: промо Meta Verified ломает подтверждение загрузки

**Дата:** 2026-06-05
**Статус:** SHIPPED + DEPLOYED (delivery main `cdf72d4`) → OP#255 Тестирование
**Репо кода:** delivery-contenthunter (`publisher_instagram.py`)
**Kill-switch:** `IG_META_VERIFIED_UPSELL_DISMISS_ENABLED` (default ON)

## Контекст: триаж упавших IG-задач (05.06)

Ранжирование IG failed-задач (`testbench=false`, окно 7–8 дней) по `error_code`.
Инфра-коды (`switch_failed_unspecified`, `adb_device_not_ready`,
`process_interrupted`, `watchdog_subprocess_hang`) — шлюз/ops, не код.

| error_code | кол-во | вывод |
|---|---|---|
| ig_account_switcher_wrong_foreground | 15 | уже закрыт прод-кодом (см. ниже) |
| ig_target_not_in_picker | 15 | ops (концентрация Мурат/septizim) |
| ig_caption_screen_not_reached | 15 | в работе у WP#193 |
| ig_share_tap_no_progress | 11 | касался WP#181 |
| **ig_upload_confirmation_timeout** | **7** | **выбран → этот фикс (6/7 = Meta Verified)** |

### Урок: исходный лидер оказался уже исправлен

Первоначально для фикса был выбран `ig_account_switcher_wrong_foreground` (15,
размазан по проектам). При взятии в работу выяснилось, что **фикс уже в проде**:
WP#197 iter2 (split-классификация `final_fg==IG` → честный
`ig_picker_sheet_not_opened` vs реальный hijack; dismiss модалки «Сохранить
данные для входа?»; escape IG-оверлея), WP#219 (аудио-страница Reels), WP#225
(reels-escape + recheck) — всё в origin/main. Код обнулён с 02.06 (10→4→0,0,0,0),
остаток реклассифицирован в `ig_picker_sheet_not_opened` (трекается OP#251).

**Вывод на будущее:** при триаже по N-дневному окну сверять даты падений с
датами уже-задеплоенных фиксов — иначе срез захватывает до-фиксовые данные.
OP#255 перенацелен.

## Root-cause нового скоупа

После тапа «Поделиться» Instagram показывает промо-интерстишл подписки
**Meta Verified** (`metaverified.MetaVerifiedUrlHandlerActivity`):
«Получите первый месяц бесплатно», тарифы Standard/Plus, «4 500,00 KZT/месяц за
профиль», «Преимущество пробного периода», синяя CTA «Получить преимущества».

Экран перекрывает прогресс публикации. Цикл `_wait_instagram_upload` сидит на
этой активности все 30 итераций (в логе: `wait N — act=metaverified.
MetaVerifiedUrlHandlerActivity`) → таймаут → `ig_upload_confirmation_timeout` →
handoff в ручную.

- **6 из 7** падений этого кода за 8 дней — этой причины.
- Активен 05.06; размазан по 7 проектам/аккаунтам (Trinnko Study, Wanttopay,
  septizim, Александр Ткаченко…) — регион Asia/Almaty (KZT), не ops.
- Обработки в коде не было (`grep metaverified` = 0).
- **Риск:** «Поделиться» нажата (+2 ретапа) → загрузка, вероятно, идёт ЗА
  модалкой → handoff в ручную = риск ДУБЛЯ поста.

**Улики:** tasks 15617 (05.06, скрин Meta Verified), 15398 (04.06),
14007/14150 (02.06), 13483, 12341, 12186. Кнопка закрытия — `content-desc="Закрыть"`
(✕ top-left, bounds `[34,208][102,332]`); CTA «Получить преимущества» тапать нельзя.

## Фикс

`publisher_instagram.py`:

1. **pure-детектор** `_is_ig_meta_verified_upsell(ui_xml, act_line)` — по
   `topResumedActivity` (`MetaVerifiedUrlHandlerActivity`) ИЛИ текстовым маркерам
   («Получите первый месяц бесплатно» / «Преимущество пробного периода» /
   «Подписка Meta Verified»).
2. **метод** `_dismiss_ig_meta_verified_upsell(ui, act_line)` — ladder:
   ✕ (`content-desc="Закрыть"`) → coord-fallback (68,270) → `KEYCODE_BACK`.
   CTA «Получить преимущества» НЕ тапается. Возвращает True при обнаружении →
   caller `continue` и продолжает ждать честное подтверждение (загрузка за модалкой).
3. **wiring** в `_wait_instagram_upload` перед блоком обработки `ModalActivity`
   (промо — отдельная активность, не ModalActivity).
4. **kill-switch** `IG_META_VERIFIED_UPSELL_DISMISS_ENABLED` (default ON;
   `=0` → старое поведение без передеплоя).

## Тесты

TDD: 11 новых тестов (`tests/test_ig_meta_verified_upsell.py`) — детектор
(по активности / по тексту / негативы), kill-switch (default ON / off), метод
dismiss (тап «Закрыть», НЕ тап CTA, no-op без апселла, no-op при выключенном
kill-switch). Курируемый IG-набор (37 файлов) — **427 passed, 0 регрессий**.

## Деплой

- Ветка `op255-ig-metaverified-upsell` (commit `3cb50b9`), worktree от origin/main.
- Merge --no-ff в delivery main: `3e41b82..cdf72d4` (merge `cdf72d4`), push origin main.
- Прод autowarm (`/root/.openclaw/workspace-genri/autowarm`) обновлён через merge
  в main-checkout; publisher спавнится per-task → **PM2-restart не нужен**.
- Kill-switch default ON в коде → активен без правки `.env`.
- Пост-деплой: 11 тестов зелёные на прод-checkout.

## Остаток

Live-verify сутки: рост события `ig_meta_verified_upsell_dismissed`, спад
`ig_upload_confirmation_timeout`. Откат: `IG_META_VERIFIED_UPSELL_DISMISS_ENABLED=0`
или revert merge `cdf72d4`.

## Связь

- OP#251 — остаток `ig_picker_sheet_not_opened` (схлопнутый профиль), смежно.
- WP#181/#223 — postmortem-проба success (тема «опубликовано за модалкой»).
- WP#197/#219/#225 — уже-задеплоенные фиксы switcher-стадии.
