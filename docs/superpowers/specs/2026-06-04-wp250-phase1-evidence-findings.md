# WP#250 — Phase 1 Evidence Findings (decision gate)

**Дата:** 2026-06-04 · **OP#250** · canary phone #19 (testbench, TikTok)
**Статус:** Фаза 1 (evidence) ЗАВЕРШЕНА. Root-cause подтверждён. Фаза 2 = research-first → fix.

## Как снято

trace-инструментация (`_tt_trace_capture`, kill-switch `TT_INAPP_UPLOAD_TRACE_ENABLED`)
задеплоена в main инертной (default-OFF); включена ТОЛЬКО на тестбенч-стенде через
env-блок `ecosystem.testbench.config.js` (прод-публикатор реальных клиентов не
затронут — у него флага нет). Прогнано N=2 инструментированных canary-публикации
(15491, 15492) + 1 корроборирующий (15490, без trace). escape-switch
`TT_INAPP_STORY_EDITOR_ESCAPE_ENABLED` оставался OFF (Task 7 расцепил детекцию).
После сбора стенд откачен (env-флаг снят, scheduler рестарт). Артефакты: S3
`save.gengo.io/.../task15491_*` + `/tmp/wp250-evidence/`.

## Сигнатура (идентична на всех прогонах)

| Точка | Activity | UI-маркеры | 
|---|---|---|
| **A. post-switch** | `com.ss.android.ugc.aweme.social.creation.mediapicker.SocialMediaPickerActivity` | «Добавить в историю», «Текст/Флип/Недавнее», «Выберите несколько вариантов», Все/Фото/Видео, тайлы 0:56 |
| **B. story_derail #0** | тот же `SocialMediaPickerActivity` | идентичный дамп → детектор derail → BACK |
| **B. story_editor #4** | `com.ss.android.ugc.aweme.adaptation.saa.SAASceneWrapperActivity` | «Ваша история», «Автомонтаж», Шаблоны/Стикеры/Эффекты/Фильтры |

## Root cause (гипотеза 1 ПОДТВЕРЖДЕНА с точностью до Activity)

**Сразу после смены аккаунта TikTok приземляется на `SocialMediaPickerActivity` —
share-to-story медиа-пикер «Добавить в историю», а НЕ в нормальный create/камеру.**
Это источник саги: BACK с этого экрана уводит в story-галерею → `SAASceneWrapperActivity`
(in-app story-композёр «Ваша история»), откуда caption-флоу честно недостижим. Все
прошлые итерации (iter5 reset-to-feed, iter6 BACK-escape, WP#44 iter3) боролись с
СИМПТОМОМ постфактум. Примечание: 3 снятых прогона в итоге опубликовались (BACK
иногда восстанавливает), но точка рождения проблемы — пост-switch вход — стабильна.

## Лид для Фазы 2 (research-first, по решению Данила)

Switcher (`account_switcher.py`) после выхода на свой профиль тапает «+» по
**хардкод-координатам (540, 2137)** (`TikTok.plus_button.coords`, :100) и верифицирует
через `_tap_plus_and_verify` (final_step `tt_fp_editor`). На TikTok 44.x этот тап
приземляет поток на `SocialMediaPickerActivity` (story-share), хотя switcher считает,
что открыл редактор. own-profile маркеры включают «Создать историю»/«Create story»
(:2683-2684) — на профиле есть story-CTA рядом с create-«+».

**Фаза 2 (отдельный план) начинается с точечного research:**
1. Разобрать дамп `SocialMediaPickerActivity` (`/tmp/wp250-evidence/15491_post_switch_post_switch.xml`):
   найти, какой именно элемент/координата открывает НОРМАЛЬНЫЙ create (камера/галерея
   для обычного поста), а какой — story-share.
2. Разобрать `_tap_plus_and_verify` TT fast-path: куда реально приземляет (540,2137),
   почему verify считает это `tt_fp_editor`, и как отличить story-share от create.
3. Выбрать фикс (i switcher / ii entry-point / гибрид): гарантировать вход в
   нормальный create-«+», либо из `SocialMediaPickerActivity` роутить в create
   (НЕ BACK в story). TDD на реальных фикстурах + canary-вериф phone #19, новый
   kill-switch default OFF. НЕ переоткрывать iter5/iter6.

## Что задеплоено / состояние

- main `e1620d8` (merge wp250) — trace-код инертный (default-OFF), постоянный
  диагностик; впоследствии main ушёл вперёд (WP#247 phase2), мерж в истории.
- Стенд testbench: trace ВЫКЛЮЧЕН после сбора (ecosystem env-флаг снят).
- Ветка `wp250-tt-story-derail-rootcause` (origin, ребейзнута на main).
