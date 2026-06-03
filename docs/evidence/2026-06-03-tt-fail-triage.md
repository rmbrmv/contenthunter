# TikTok fail-триаж за 2026-06-03

Источник: прод host-PG `openclaw` (localhost:5432), таблица `publish_tasks`.
Окно: `created_at` (UTC) приведён к Europe/Moscow, дата = 2026-06-03.
Платформа: `platform='TikTok'`.

## Распределение статусов (МСК-сегодня)

| status | count |
|---|---|
| failed | 27 |
| done | 17 |
| pending | 2 |
| running | 2 |
| awaiting_url | 1 |
| published_no_url | 1 |

Success-rate ≈ 17/(17+27) ≈ 39% по завершённым.

## Упавшие задачи (failed=27) по коду ошибки

| # | error_code | error_class | count | оценка |
|---|---|---|---|---|
| 1 | **tt_publish_button_not_activated** | ui_changed | **9** | **код-фикс (выбрано)** — ложный fail, см. ниже |
| 2 | adb_device_not_ready | device_unreachable | 8 | инфра/девайс — покрыто WP#195 (gate) / WP#210 (throttle) |
| 3 | tt_inapp_upload_unreached | ui_changed | 3 | на верификации (WP#203 iter5, shipped 02.06) |
| 4 | phone_or_email_link_required | banned | 3 | бан/блок аккаунта — не код-баг (ops) |
| 5 | tt_caption_field_not_focused | ui_changed | 2 | семейство WP#203 |
| 6 | tt_account_sheet_closed_before_parse | ui_changed | 1 | длинный хвост |
| 7 | tt_storyservice_fg_stuck | ui_changed | 1 | длинный хвост |

Наибольший объём код-фиксабельных падений даёт **`tt_publish_button_not_activated` — 9/27 (33%)**.
(adb_device_not_ready=8 — это инфраструктурная недоступность девайса, уже имеет код-обвязку
WP#195/#210; phone_or_email_link_required=3 — бан аккаунта, решается через ops.)

## Корень `tt_publish_button_not_activated` (ложный fail)

### Затронутые задачи
14727, 14765, 14770, 14792, 14797, 14807, 14809, 14812, 14819 — 9 разных
устройств / аккаунтов / проектов (не девайс-специфично, не аккаунт-специфично).

### Что показывают логи (единый паттерн)
```
TikTok: кнопка публикации найдена (descendant) pos=(798, 2103)
TikTok: пост-тап дамп неинформативен (ни success, ни редактор)
ai_find_tap_no_coords: desc='the final Publish button ...' resp='{"x": null,...}'
TikTok: кнопка — FALLBACK (816, 2130), XML не нашёл
TikTok: пост-тап дамп неинформативен (ни success, ни редактор)   ← x6-7 циклов
...
ERROR  TikTok: кнопка «Опубликовать» не активирована (экран редактора не сменился после тапа)
ERROR  Публикация завершилась с ошибкой
HANDOFF Изменился интерфейс приложения — задача передана на ручную выкладку.
```

### Что показывают скриншоты/скринкасты (`*_fallback_step7_*.png`)
- **14727**: фид «Друзья» + модалка **«Включить уведомления о взаимодействиях с
  публикациями?»** (кнопка «Получать уведомления»). Контент уже опубликован.
- **14807**: фид + модалка **TikTok Amplify «Пусть вас заметят»** («Откройте для
  себя TikTok Amplify» / «Не сейчас»). Контент уже опубликован.
- **14770**: экран **«Входящие»** (дрейф после слепых retap по нижней навигации).
- **14792**: экран **«Отображение профиля»** (бизнес-настройки, дрейф).

Скринкаст task14727 (405 c) покадрово подтверждает таймлайн:
- t≈265 c: финальный экран постинга с красной кнопкой **«Опубликовать»**.
- t≈320 c: уже **фид «Друзья» + модалка «Включить уведомления…»** — публикация прошла,
  приложение ушло на фид, появилась пост-публикационная модалка.

→ Тап по «Опубликовать» **срабатывает**, публикация **проходит**, но появляется
пост-публикационная промо-модалка, перекрывающая success-маркеры фида.

### Точное место в коде (`publisher_tiktok.py`, прод-каталог autowarm)
1. После тапа вызывается gate `_tt_verify_publish_left_editor()` (WP#218, H1).
2. Gate принимает «ушли из редактора» только при позитивном
   `_tt_screen_indicates_publish_done(vui)` → проверяет лишь:
   - `_tt_post_publish_success_screen` (маркеры фида/профиля `_TT_PUBLISH_SUCCESS_MARKERS`),
   - `_detect_tt_visibility_confirm_dialog`,
   - `_detect_tt_music_rights_dialog`.
3. Пост-публикационные модалки **«уведомления»** и **«TikTok Amplify»** в этот
   предикат **НЕ включены**. Когда они висят поверх фида, success-маркеры срезаны →
   `_tt_screen_indicates_publish_done=False`, при этом это и не misfire-subscreen, и
   не pre-publish → ветка «дамп неинформативен» → `return False` → повторный тап.
4. Эти же модалки **уже обрабатываются ниже в wait-loop** (notification → KEYCODE_BACK,
   стр. ~3509 «FIX T9»; Amplify dismiss → inferred_success, стр. ~1616), НО поток до
   wait-loop **не доходит**: WP#218-gate раньше отклоняет тап и зацикливает retap →
   исчерпание попыток → честный `tt_publish_button_not_activated` → handoff в ручную.

### Это отложенный follow-up «H2» самого WP#218
Спека `2026-06-02-wp218-tt-publish-button-not-activated-design.md`, раздел «Остаток»:
> H2 (false-negative детекции, 15%) — отдельный фоллоу-ап: дисмисс модалки … в
> wait-loop + хардненинг stale-uiautomator на профиле (зеркало WP#181).

WP#218 закрыл H1 (слепой тап мимо кнопки — реальный mis-fire). После его деплоя
доминирующим стал именно отложенный H2: публикация прошла, но детекция ложно-негативна
из-за пост-публикационных модалок. Сегодня это 9/27 (33%) падений TikTok.

### Последствия
- Ложный fail успешно опубликованного контента.
- Handoff в ручную выкладку → риск **дубля публикации** оператором.
- Искажение метрики успешности TikTok вниз.

### Направление фикса (для исполнителя)
Расширить позитивный предикат публикации (`_tt_screen_indicates_publish_done` или
`_tt_post_publish_success_screen`) детектом пост-публикационных модалок «уведомления»
(`Включить уведомления о взаимодействиях с публикациями` / `Получать уведомления`) и
TikTok Amplify (`Пусть вас заметят` / `TikTok Amplify`) — они появляются ТОЛЬКО после
успешного тапа «Опубликовать» (уже задокументировано в коде, WP#118 r2 / FIX T9). Тогда
WP#218-gate вернёт True → поток дойдёт до wait-loop, который дисмиссит модалку и
подтвердит UPLOAD_OK. Отдельный kill-switch, TDD на pure-хелперах, без регрессий H1.

---

## Статус: SHIPPED+DEPLOYED 2026-06-03 (WP#226)

Фикс реализован (TDD) и задеплоен в тот же день:
- delivery-contenthunter PR **#149** → merged, main `254930c`.
- Прод-каталог `/root/.openclaw/workspace-genri/autowarm` обновлён `git pull --rebase` (ff), фикс присутствует, PM2-restart не нужен (publisher per-task spawn).
- Kill-switch `TT_PUBLISH_POSTMODAL_SUCCESS_ENABLED` default ON, в прод-`.env` не переопределён.
- Smoke 21/21 (WP#226-подмножество) на прод-checkout зелёный.
- OpenProject **WP#226 → Тестирование**.
- Спека: `docs/superpowers/specs/2026-06-03-wp226-tt-publish-postpublish-modal-design.md` (в PR #149).
- Остаточный follow-up (stale/markerless dump на профиле, зеркало WP#181) занесён в `agents/genri/BACKLOG.md`.

Verify: утренней пачкой по убыли `tt_publish_button_not_activated`.
