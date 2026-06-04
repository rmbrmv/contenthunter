# WP#250 — TikTok story-derail: реальный root-cause (evidence-first)

**OpenProject:** OP#250 (тип «Ошибка», проект Content Hunter, assignee `danil`, статус «В разработке»)
**Follow-up к:** OP#248 (mitigation — откат iter6, story-editor BACK-escape выключен дефолтом)
**Дата:** 2026-06-04
**Ветка:** `wp250-tt-story-derail-rootcause`

## Проблема

После смены аккаунта TikTok оказывается на share-экране «Добавить в историю»
(`SocialMediaPickerActivity`) → нормальный пост-флоу (caption-экран) не достигается.
Сага WP#44 iter3 / WP#203 iter4–6 — **6 итераций фикса вслепую**, все провалились,
потому что **ни разу не была снята живая сигнатура реального экранного перехода
после switch**. Фаза upload-escape не выгружала XML-дампы в S3 → от 41 провала
iter6 остался лишь финальный дамп, а не последовательность экранов.

### Что уже пробовали и НЕ помогло
- **iter5** (ветка g, reset-to-feed `am start`) → `tt_inapp_upload_unreached`.
- **iter6** (ветка a3, BACK-escape story-editor) → `tt_story_editor_unrecoverable`,
  0 восстановлений из 41, регрессия done-rate TikTok 32%→10% → **откачено (OP#248)**.
- **WP#44 iter3** (story-derail early dismiss) → canary 9–10/10 снова fail.

И BACK, и reset-to-feed борются с симптомом постфактум.

## Принцип решения: evidence-first

**Не писать фикс, пока не увидим реальную сигнатуру экранов.** Двухфазный план
с обязательным decision gate между диагностикой и фиксом.

```
Фаза 1: EVIDENCE                    ┌─ DECISION GATE ─┐    Фаза 2: FIX
1. trace-инструментация             │ показать Данилу │    4. фикс по фактам
   _tt_inapp_upload_from_camera ──► │ снятую          │ ─► (switcher / entry /
   + пост-switch snapshot           │ сигнатуру:      │     пост-switch nav)
2. canary на phone #19              │ activity-трейс  │    5. TDD + canary-вериф
   (testbench, idx=1, реальная      │ + XML экранов   │       phone #19
   публикация)                      │ → выбор фикса   │    6. прод-деплой за
3. сбор дампов S3 + events          └─────────────────┘       kill-switch
```

## Архитектура и контекст кода

- `_ensure_correct_account()` (`publisher_base.py:1961`) делегирует в
  `self.switcher.ensure_account()`; **сам switcher** после смены аккаунта тапает
  «+» на профиле, чтобы открыть редактор/галерею
  (`publisher_tiktok.py:3217-3219`).
- Если редактор не задетектился по маркерам (`publisher_tiktok.py:3231-3234`),
  запускается стейт-машина `_tt_inapp_upload_from_camera()`
  (`publisher_tiktok.py:1408`) с ветками: a caption / a2 profile / a3 story-editor
  (выключена) / b editor / c story-derail / d gallery / e camera / f feed «+» /
  g unknown-reset.
- Артефакты: `_save_debug_artifacts(label)` (`publisher_base.py:1005`) льёт
  скриншот+XML в S3, но **только в терминальных точках фейла**.

## Фаза 1 — инструментация evidence

Всё за новый kill-switch **`TT_INAPP_UPLOAD_TRACE_ENABLED`** (default OFF в проде,
ON только на тестбенче во время canary). Новый хелпер
`_tt_trace_capture(label, branch, upload_iter)` — одна ответственность: снять
XML+скрин+activity, залить в S3, залогировать событие; не падает при недоступном
S3; уважает kill-switch. Вызывается из 3 точек, **сам цикл состояний не
переписывается**:

**A. Пост-switch snapshot** — сразу после `_ensure_correct_account()` вернул True
(`publisher_tiktok.py:3231`, перед проверкой `in_editor`):
- `dumpsys activity activities | topResumedActivity` → реальная Activity.
- XML+скриншот в S3; событие `tt_trace_post_switch`
  (`meta.activity`, `meta.dump_url`).
- → прямая проверка **гипотезы 1** (оставляет ли switcher на share-экране).

**B. Per-iteration trace** в `_tt_inapp_upload_from_camera` (цикл `for it in
range(12)`, `:1429`): на каждой итерации, сматчившей ветку **d (story-derail)**,
**a3 (story-editor)** или **g (unknown)** — снимаем XML+скрин+activity в S3 **до**
действия (BACK/reset). Событие `tt_trace_state` (`meta.upload_iter`,
`meta.branch` ∈ `story_derail`/`story_editor`/`unknown`, `meta.fg_pkg`,
`meta.dump_url`).
- → закрывает **гипотезу 3** (последовательность экранов, которую iter6 терял).

**C. Сводка в конце** — список всех `dump_url` в терминальном событии, чтобы из
одного события собрать всю траекторию.

**Постоянство:** trace остаётся в коде как kill-switched диагностика (НЕ
throwaway) — окупится при будущих TT-триажах. Default OFF → ноль накладных в проде.

## Фаза 1 — прогон canary и изоляция

- Код инструментации — ветка `wp250-tt-story-derail-rootcause` в
  `delivery-contenthunter`, база свежий `main`, изолированный worktree
  (не мешать параллельным сессиям).
- Тестбенч phone #19 обслуживается **отдельным** PM2-приложением
  `autowarm-testbench` (`testbench_scheduler.js`), которое спавнит `publisher.py`
  из чекаута `/home/claude-user/autowarm-testbench/` (владелец claude-user, НЕ
  прод, НЕ root-овый autowarm). Сейчас чекаут на устаревшей ветке `wp216`.
- На время canary-окна: проверить `system_flags.testbench_paused`, согласовать
  окно, перевести чекаут на ветку WP#250 (попутно стенд получает актуальный
  main-код), выставить `TT_INAPP_UPLOAD_TRACE_ENABLED=true` в его `.env`. После
  сбора — вернуть чекаут/env как было.

**Прогон:**
1. `testbench_orchestrator.tick({'idx':1})` из тестбенч-дир (`PLATFORMS=
   ['Instagram','TikTok','YouTube']` → idx=1 = TikTok) создаёт реальную
   TikTok-задачу (свежий аккаунт+seed-видео phone #19; сырой requeue не работает —
   media_path обнулён post-cleanup → именно `tick`).
2. Тестбенч-скедулер публикует инструментированным кодом → derail
   воспроизводится → trace льётся в S3.
3. **N=3–5 прогонов** (derail флаки — нужна выборка для стабильной сигнатуры).
4. Сбор `tt_trace_*` событий из host-PG (localhost:5432, НЕ Docker) + дампы из S3.

**Выход фазы 1:** таблица «итерация → activity → ключевые узлы XML → ветка
стейт-машины» по всем прогонам + скриншоты — артефакт для decision gate.

## Decision gate

Останавливаюсь, показываю Данилу сводную таблицу траектории + скриншоты. Три
заранее очерченных исхода (какой подтвердится — покажут факты):

- **(i) Корень в switcher** — `ensure_account` приземляет на share/story-Activity.
  Фикс в модуле switcher: гарантировать чистую ленту/профиль перед сдачей
  управления.
- **(ii) Корень в точке входа** — лента достижима, но вход в upload идёт через
  story-галерею. Фикс: входить «+»→create из ленты.
- **(iii) Корень в пост-switch навигации** (`tt_post_switch_handle_unknown` /
  `recovered_via_renav`) — приземление в share-flow. Фикс в источнике навигации.

**Конкретный фикс (i/ii/iii или гибрид) согласуется с Данилом на гейте, прежде
чем писать код.** НЕ переоткрывать iter5/iter6 как есть.

## Фаза 2 — реализация фикса (TDD)

1. Red-тесты на снятую сигнатуру (фикстуры — реальные XML-дампы из canary).
2. Фикс за **новым** kill-switch (default OFF до canary-верификации) — чтобы не
   повторить регрессию iter6 (done-rate 32%→10%).
3. Регрессия TT-набора зелёная.
4. **Canary-верификация на phone #19**: реальная публикация проходит до
   caption-экрана, `/video/` URL появляется, событий derail нет.
5. Прод-деплой только после успешной canary; включение kill-switch дефолтом —
   отдельным шагом после суток наблюдения.

## Тестирование

- Фаза 1: TDD на `_tt_trace_capture` (снимает/логирует/не падает при недоступном
  S3; respects kill-switch).
- Фаза 2: TDD на детектор/навигацию по реальным фикстурам canary.

## Вне scope (YAGNI)

- Не рефакторим стейт-машину целиком.
- Не трогаем Instagram/YouTube.
- Не переоткрываем откаченные ветки iter5/iter6 как есть.
