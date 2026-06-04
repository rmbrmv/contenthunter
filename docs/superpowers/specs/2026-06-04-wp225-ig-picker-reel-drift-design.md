# WP#225 — IG `ig_picker_sheet_not_opened`: дрейф профиля в рилс (follow-up PR#150)

**Дата:** 2026-06-04
**OpenProject:** WP#225 (переоткрыт из «Тестирование» → «В разработке» 04.06 07:53)
**Тип:** Ошибка · Платформа: Instagram · Репо кода: `delivery-contenthunter` (`account_switcher.py`)
**Статус спеки:** утверждена (брейншторм с Данилом 04.06)

## 1. Контекст и почему задача переоткрыта

Исходный фикс WP#225 — PR #150 (`_ig_poll_account_switcher_sheet`, kill-switch `IG_PICKER_SHEET_RECHECK_ENABLED`, default ON, смержен `2ac722e`, задеплоен 03.06 ~12:06 МСК) — добавил **пост-тап poll**: после тапа по шапке профиля sheet выбора аккаунта мог открыться/догрузиться не мгновенно, а top-of-loop ре-чек на последней итерации `range(2)` отсутствовал → ложный `ig_picker_sheet_not_opened`.

Этот фикс **корректен для исходной спеки** и поймал бы пре-деплойные кейсы:
- **task 14646** (02.06, ClickPay): финальный тап реально открыл sheet — в дампе `ig_3_open_list_sheet_reguard_1` есть `recycler_view_container_id` + футер «Добавьте аккаунт Instagram»/«Перейти в Центр аккаунтов» + целевой `clickpay_world`. Poll бы вернул True.
- **task 14746** (03.06, тест-проект): sheet завис на спиннере загрузки — poll дождался бы.

**Но живые рецидивы после деплоя — другой корень**, поэтому задачу переоткрыли.

## 2. Корень живых рецидивов (smoking gun)

Пост-деплойные фейлы (после 03.06 12:06 МСК), у всех `recheck_ok=false`:

| task | время МСК | проект | финальный экран |
|------|-----------|--------|-----------------|
| 15234 | 04.06 10:28 | Lexis Voice_16a (клиент) | рилс-пост на профиле |
| 15071 | 03.06 14:23 | Тестовый_171b (тест) | пустой дамп |
| 15049 | 03.06 13:33 | Splus_70a (клиент) | рилс-пост на профиле |

Последовательность у всех трёх идентична: `ig_picker_fg_probe` (fg=IG, ОК) → `ig_picker_wrong_screen` (attempt 0) → `ig_picker_wrong_screen` (attempt 1) → `ig_picker_sheet_not_opened`. **Ни одна существующая escape-ветка не сработала** (нет `*_overlay_escaped` / `*_audio_page_escaped` / `*_modal_dismissed` / `*_fg_drift`), и poll ни разу не распознал sheet.

**Механизм (дамп task 15234 `ig_4_sheet_reguard_0`):**
- «Профиль» на самом деле показывает **сетку Reels от самого верха**: элементы `content-desc="Видео Reels … в строке 1, столбце 1/2/3"` с `bounds.top = 102` (< `header_y_max ≈ 260`). Единственный текст на экране — «4». **Тайтл-бара с username (шеврон switcher'а) нет** — он схлопнут/не отрисован (на экране ещё `swipe_refresh_animated_progressbar` — профиль обновляется).
- `_tap_profile_header` не находит username-токен в зоне `y < header_y_max` → выполняет **слепой fallback-тап `(540, 180)` и безусловно возвращает `True`**.
- Координата `(540, 180)` попадает **в ячейку рилс-грида** (грид занимает `y=102…577` на этом `x`) → открывается рилс-пост → дрейф.
- Attempt 1 уже на рилс-посте (`row_feed_profile_header`, `feed_preview_bottom_cta_container`, тексты «Продвигать публикацию»/«Смотреть снова»/«… · Оригинальное аудио») — у этого оверлея **нет escape-ветки** (он не входит в `_IG_INAPP_OVERLAY_MARKERS` и не является audio-страницей) → повторный слепой тап → исчерпание `range(2)` → `ig_picker_sheet_not_opened`.

Сравнение со спекой PR#150:

| | Исходная спека (14646/14746) | Живые рецидивы (15234/15071/15049) |
|---|---|---|
| Sheet | реально открыт / грузится | **не открывается вовсе** |
| Куда ушли | — | дрейф в рилс на профиле |
| Лечит PR#150-poll? | да | нет (sheet нет → poll корректно False) |

## 3. Решение (Подход 1: профилактика дрейфа + escape)

Три части, все в `delivery-contenthunter/account_switcher.py`, под единым kill-switch `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED` (**default ON**). PR#150-poll остаётся без изменений.

### 3.1. Детектор `_ig_on_profile_reel_drift(elements, header_y_max)` — pure
True, если профиль задрейфовал в рилс. **Исключает sheet** (приоритет — как у `_ig_on_inapp_overlay`/`_ig_on_audio_page`). Две под-формы:

- **Грид-от-верха** (15234 attempt 0): среди `elements` есть рилс-ячейка грида (`content-desc` матчит маркер «Видео Reels … в строке N, столбце M», устойчивый русский/англ. паттерн сетки) с `bounds.top < header_y_max` **И** в тайтл-зоне (`y < header_y_max`) НЕТ username-элемента (`_looks_like_username`). Позиционность критична: на нормальном профиле грид всегда есть, но **ниже** био/статистики (`top > header_y_max`), а username-тайтл присутствует → false.
- **Рилс-пост открыт** (15234 attempt 1 / 15049): присутствуют `row_feed_profile_header` **и** `feed_preview_bottom_cta_container` (контейнерные маркеры feed-просмотра поста на профиле). Текстовые «Смотреть снова»/«Продвигать публикацию» — вспомогательные, не обязательные (устойчивее по resource-id).

Чистая функция над списком `UIElement` (с `bounds`) — тестируется в изоляции.

### 3.2. Escape-ветка в `_ig_guard_picker_foreground` (reguard-цикл)
Новый `elif` **после** audio-page-ветки (~стр. 2261), строго по образцу WP#219:
```text
elif _ig_picker_reel_drift_escape_enabled() and self._ig_on_profile_reel_drift(elements, header_y_max):
    log_event 'ig_picker_reguard_reel_drift_escaped' (meta.category, step=ig_4_pick_account, attempt)
    adb KEYCODE_BACK            # выходит из рилс-поста; на гриде-от-верха корректируется ре-навом
    sleep POST_TAP_WAIT_S
    _go_to_profile_tab(cfg, 'ig_2_profile_tab_reel_drift_escape')   # ре-тап profile-таба → скролл-в-верх, username-тайтл восстанавливается
    sleep POST_TAP_WAIT_S
```
Далее в **той же** итерации существующие `_read_screen_hybrid` + `_tap_profile_header` отрабатывают по восстановленному профилю-верху → шапка тапается → sheet открывается → PR#150-poll его ловит → `True`.

> **Замечание по `elements`:** ветка детекта вызывается внутри harden-блока, где переменная `xml` уже есть (top-of-loop `dump_ui`). Для позиционного детекта нужен парсинг `elements` из этого `xml` (`parse_ui_dump(xml)`) — детектор принимает уже распарсенные `elements`.

### 3.3. Подавление слепого fallback-тапа в `_tap_profile_header`
Когда username не найден **и** зона хедера занята рилс-гридом (`_ig_header_zone_has_reel_grid(elements, header_y_max)`), **не делать** `adb_tap(*fallback_coords)` (это и есть источник дрейфа) — вернуть `False`. Caller (`_ig_guard_picker_foreground`) на `False` делает `break` → честный выход без «успешного» дрейфа в рилс.

На нормальном профиле (username просто не распарсился, грида в зоне хедера нет) слепой fallback-тап **сохраняется без изменений** — минимизация регресс-риска. Поведение под тем же kill-switch.

## 4. Безопасность

- **Cross-project-leak:** escape — только `KEYCODE_BACK` + ре-нав; **тапов по чужому видео-контенту нет**. Подавление слепого тапа строго безопаснее (убирает тап в рилс). Соблюдён инвариант «чужое видео не ре-тапаем».
- **Risk-асимметрия детектора:** ложный positive `_ig_on_profile_reel_drift` → лишний BACK+ре-нав (вернёмся на профиль-верх, безвредно). Ложный negative → остаётся текущий баг. Поэтому маркеры подобраны на реальных дампах, но детект **позиционный**, чтобы не фолзить на нормальном профиле.
- **Kill-switch** `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED` (default ON) полностью отключает обе новые ветки (escape + подавление тапа) — мгновенный откат без передеплоя.

## 5. Тестирование (TDD)

Pure-юниты (фикстуры из реальных S3-дампов):
- `_ig_on_profile_reel_drift`:
  - грид-от-верха 15234 attempt0 → **True**;
  - рилс-пост 15234 attempt1 / 15049 → **True**;
  - нормальный профиль (username-тайтл + грид ниже хедера) → **False**;
  - sheet-дамп 14646 (`recycler_view_container_id`+футер) → **False** (приоритет sheet);
  - audio-страница / in-app overlay → **False** (не пересекаемся).
- `_ig_header_zone_has_reel_grid` / `_tap_profile_header`:
  - грид-в-зоне-хедера без username → fallback подавлён, `False`;
  - нормальный профиль без распознанного username, без грида в хедере → старый fallback `True`.
- Регрессия: существующий набор IG-тестов switcher — зелёный (особое внимание escape-веткам WP#197/#219, чтобы новая ветка стояла после них и не перехватывала их кейсы).

## 6. Деплой и верификация

- Деплой как обычно для autowarm: PR в `delivery-contenthunter` main → прод-autowarm `/root/.openclaw/workspace-genri/autowarm` `git pull` (publisher спавнится per-task, PM2-restart не нужен).
- Верификация сутки: рост события `ig_picker_reguard_reel_drift_escaped` + падение `ig_picker_sheet_not_opened` у реальных клиентов (Lexis Voice, Splus). Тест-проект Тестовый_171b — артефакт утечки scheme_preview (см. WP#217), из метрики реального успеха исключить.

## 7. Вне scope (follow-up при необходимости)

- Почему профиль открывается схлопнутым/в Reels-таб с грид-от-верха (root-cause навигации до switcher'а) — текущий фикс делает шаг устойчивым к этому состоянию, но не устраняет первопричину появления состояния. Если после деплоя `ig_picker_reguard_reel_drift_escaped` будет частым — завести follow-up на навигацию `_go_to_profile_tab` → switcher.
