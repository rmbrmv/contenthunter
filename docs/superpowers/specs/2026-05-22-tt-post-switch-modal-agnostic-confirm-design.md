# TikTok post-switch verify — единый modal-agnostic confirm (WP #67, Layer 3)

**Дата:** 2026-05-22
**WP:** OpenProject #67 (Ошибка) — `tt_post_switch_verify_unrecoverable`
**Репозиторий кода:** GenGo2/delivery-contenthunter, `account_switcher.py` (testbench → prod autowarm)
**Предыдущие слои:** Layer 1 (приоритет @-логина, PR #62, 14.05) · Layer 2 (whitelist dismiss промо-модалок, PR #70, 18.05)

---

## 1. Проблема

После переключения аккаунта TikTok робот проверяет, что открылся именно нужный аккаунт, читая @-логин с экрана профиля. После двух слоёв защиты остаточные падения `tt_post_switch_verify_unrecoverable` держатся на уровне **1–3/сутки** (19.05=1, 20.05=3, 21.05=1, 22.05=2) и не закрываются прошлыми фиксами.

Разбор скринкастов 6 свежих падений (9124, 9190, 8573, 8616, 8685, 7715) показал **три различных под-режима**, у которых **общий корень**: переключение по факту проходит (на скринкасте 9124 виден баннер TikTok «Вы вошли как WellroomCare» — целевой аккаунт), но проверку сбивает модалка или переходный экран. Это **ложные отказы**.

| Под-режим | Задачи | Цепочка событий | Что на экране |
|---|---|---|---|
| **A. Модалка поверх ленты ломает renav** | 9124, 8685 | `feed_after_pick → renav_failed → verify_unrecoverable` | Свитч удался, лента, сверху модалка «Подпишитесь на друзей» перекрывает bottom-nav → вкладка «Профиль» не нажимается |
| **B. Переходный/loading-экран** | 8573, 9190 | `verify_unrecoverable` (без feed) | Шторка «Сменить аккаунт» ещё видна + спиннер, профиль не дочитан; ни feed-маркеров, ни чистого @-логина → мгновенный fail «non-feed» |
| **C. Лента→renav прошёл, но профиль перекрыт** | 7715, 8616 | `feed_after_pick → verify_unrecoverable` | Лента, renav сработал, затем всплыла «Быстрая проверка безопасности» → профиль не читается |

**Важно:** во всех трёх TikTok остаётся на переднем плане — это **НЕ** foreground-drift (территория WP #130).

### Почему текущая защита не покрывает

1. **Whitelist слишком узкий** — `_TT_POST_SWITCH_DISMISSIBLE_MODALS` не содержит «Подпишитесь на друзей» и «Быстрая проверка безопасности».
2. **Тайминг** — probe-сайты `pre_feed`/`post_renav` не покрывают момент между feed-detect и renav-тапом (модалка вылезает там и блокирует сам тап во вкладку профиля — под-режим A).
3. **Нет settle-retry** — проверка читает экран в переходном состоянии и сразу падает (под-режим B).
4. **Fail-closed без сигнала успеха** — не смогли прочитать @-логин → считаем свитч провалившимся, хотя баннер TikTok прямо подтверждает успех.

---

## 2. Подход: единый modal-agnostic confirm

Принцип сохраняется **fail-closed**: не подтвердили успех И не нашли чем закрыть → честный fail; прочитали ЧУЖОЙ аккаунт → mismatch (существующий cold-restart re-pick). Но добавляем три независимых, отключаемых kill-switch'ом кирпича, бьющих по общему корню.

Каждый кирпич — самостоятельный, тестируемый изолированно хелпер с чётким интерфейсом. Существующий whitelist Layer 2 поглощается кирпичом 2.

### Кирпич 1 — ловля баннера «Вы вошли как X» (best-effort, screen-independent)

Самый сильный сигнал успеха: TikTok сам показывает баннер подтверждения сразу после переключения, независимо от того, на какой экран приземлились.

- **Хелпер (модульный, чистая функция):** `_tt_read_login_confirm_banner(xml) -> Optional[str]`
  - Ищет текст по паттернам (case-insensitive): `(?:вы\s+)?вошли\s+как\s+(.+)`, `logged\s+in\s+as\s+(.+)`, `switched\s+to\s+(.+)`. Возвращает извлечённый handle (без `@`, нормализованный) или `None`.
- **Где зовётся:** на раннем dump'е сразу после тапа по аккаунту в picker'е (баннер живёт ~2с — снимаем до `AFTER_SWITCH_WAIT_S`, отдельным быстрым dump'ом), и повторно внутри recovery на каждом re-dump'е.
- **Эффект:** если извлечённый handle ≈ target → авторитетный `match`, **минуем чтение профиля целиком**.
- **Неизвестность (снимается на тестах):** не подтверждено, что баннер попадает в accessibility-дерево uiautomator. Поэтому строго best-effort: не поймали → проваливаемся в обычный путь. Перехватываемость проверяется первым же re-queue (см. §6).
- **Kill-switch:** env-var `TT_POST_SWITCH_BANNER_DISABLED=1` → хелпер всегда возвращает `None`.

### Кирпич 2 — generic modal-dismiss loop (ядро modal-agnostic)

Вместо whitelist пар `(заголовок, кнопка)` — детект по **консервативному списку безопасных dismiss-кнопок**. Новые модалки почти всегда переиспользуют те же кнопки закрытия, поэтому список кнопок устойчивее списка заголовков.

- **Хелпер (модульный):** `_tt_find_safe_dismiss(xml) -> Optional[tuple[str, tuple[int,int]]]`
  - Возвращает `(label, (cx, cy))` первого clickable-элемента, чей нормализованный `label`/`content-desc` ∈ **SAFE_DISMISS**, иначе `None`.
  - **SAFE_DISMISS** (нормализация: lower, strip): `не сейчас`, `закрыть`, `не разрешать`, `пропустить`, `отмена`, `позже`, `not now`, `close`, `skip`, `cancel`, `don't allow`, `dismiss`, `later` + content-desc `Закрыть`/`Close` (крестик).
  - **Исключаются** affirmative-кнопки: `продолжить`, `разрешить`, `ок`/`ok`, `подписаться`, `открыть настройки`, `allow`, `continue`, `follow`. Это гарантирует: тап dismiss не подпишет на аккаунты, не выдаст пермишены, не запустит security-флоу.
  - Match только если элемент в нижней или центральной части экрана (исключаем случайные совпадения в контенте ленты): требуем `clickable=true` и достаточный размер кнопки.
- **Цикл (cap = `TT_DISMISS_MAX`, default 2):** экран не подтверждён → найти safe-dismiss → тап → `time.sleep(POST_TAP_WAIT_S)` → re-dump → повторный confirm (баннер + чтение профиля). Match → recovered. Safe-кнопки нет → выход из цикла (проваливаемся дальше).
- **Где зовётся:** на всех probe-сайтах recovery **+ новое:** между feed-detect и renav (тайминг под-режима A) и **перед** тапом во вкладку профиля (`_navigate_to_profile_tab`), чтобы модалка не блокировала bottom-nav.
- **Поглощение Layer 2:** старый `_tt_try_dismiss_post_switch_modal` + whitelist остаются как fallback, но основной путь — generic. Whitelist можно оставить пустым (его кейсы покрывает SAFE_DISMISS).
- **Kill-switch:** env-var `TT_POST_SWITCH_GENERIC_DISMISS_DISABLED=1`.

### Кирпич 3 — settle-retry для переходных/loading-экранов (под-режим B)

- Перед вердиктом «unknown → fail»: если на экране **маркер незавершённого свитча** — шторка `Сменить аккаунт`/`Управление аккаунтами` всё ещё присутствует, либо progress/loading-нода — то подождать `TT_SETTLE_S` (default 1.5с) и re-dump, до `TT_SETTLE_RETRIES` (default 2) раз. На каждой итерации заново прогоняем confirm (баннер + профиль + generic-dismiss).
- Падаем `verify_unrecoverable` только если после settle экран так и не подтвердился. Если за это время откроется чужой аккаунт — честный `mismatch` → существующий cold-restart re-pick.
- **Хелпер:** `_tt_screen_is_transitional(xml) -> bool` (детект маркеров).
- **Kill-switch:** env-var `TT_POST_SWITCH_SETTLE_DISABLED=1`.

---

## 3. Новый поток recovery

Перерабатывается `_tt_handle_post_switch_unknown(target, xml_after_pick, header_y_max, label, attempt)`:

```
0. confirm(xml_after_pick): banner-check → если match, return recovered
1. generic-dismiss loop на текущем xml → confirm после каждого dismiss → match? recovered
2. settle-retry если transitional → confirm на каждом re-dump → match? recovered ; чужой? mismatch
3. feed-detect:
     если feed:
        generic-dismiss (на случай модалки поверх ленты)
        renav (_navigate_to_profile_tab)
        re-dump → generic-dismiss → confirm
        match? recovered ; mismatch? mismatch
4. остаток → честный _fail('tt_post_switch_verify_unrecoverable: ...')
```

`confirm(xml)` = вспомогательная: сначала `_tt_read_login_confirm_banner` (если ≠None и ≈target → match), затем существующий `_post_switch_verify_handle`. Возвращает `('match'|'mismatch'|'unknown', current)`.

Вызывающий код в `_switch_tiktok` (строка ~2846) не меняется по контракту: `outcome ∈ {recovered, mismatch, failed}`. Ранний banner-check добавляется также в основной цикл сразу после pick (кирпич 1).

---

## 4. Безопасность и откат

- **Fail-closed сохраняется:** ничего не подтвердило успех и нет safe-dismiss → честный `tt_post_switch_verify_unrecoverable`. Никакого degrade-to-pass.
- **Mismatch-детект цел:** dismiss → re-read; если прочитан другой @-логин → mismatch → cold-restart re-pick (без изменений).
- **3 независимых env-kill-switch** (`BANNER`, `GENERIC_DISMISS`, `SETTLE`). Все включены OFF → поведение ≈ текущему. Откат без редеплоя.
- **SAFE_DISMISS консервативен** — только негативные/закрывающие действия. Affirmative-кнопки явно исключены.
- `TT_DISMISS_MAX`, `TT_SETTLE_S`, `TT_SETTLE_RETRIES` — env-tunable.

---

## 5. Телеметрия

- `tt_post_switch_confirmed_via_banner` (`account_switch`) — meta: `target`, `banner_handle`, `probe_site`.
- `tt_post_switch_modal_dismissed_generic` (`account_switch`) — meta: `button_label`, `probe_site`, `attempt`.
- `tt_post_switch_blocked_no_safe_button` (`warning`) — экран не подтверждён, но safe-кнопки нет. **Новый сигнал триажа:** показывает, какую модалку/кнопку не покрыли (вместо «добавь заголовок в whitelist» — «добавь label в SAFE_DISMISS»).
- `tt_post_switch_settle_retry` (`info`) — meta: `attempt`, `markers`.
- Терминальный `tt_post_switch_verify_unrecoverable` сохраняется как есть (для совместимости дашбордов и 24h-метрик).

---

## 6. Тестирование

### Фикстуры (источник — re-queue, решено с пользователем)

Дампы 6 упавших задач уже ротировались с диска. Перевыкладываем 1–2 задачи (например 9124 — под-режим A, 7715 — под-режим C) через `publish_queue` (UPDATE → pending, publish_task_id=NULL; dispatchPublishQueue создаст новый pt). Цели:
1. Поймать реальные post-switch UI-дампы → сохранить как fixtures в `tests/fixtures/`.
2. **Подтвердить перехватываемость баннера** «Вы вошли как X» в dump'е (решает неизвестность кирпича 1). Если баннер не в дереве — кирпич 1 остаётся под kill-switch выключенным, фикс опирается на кирпичи 2+3.

### Unit-тесты (`tests/test_tt_post_switch_modal_agnostic.py`)

- `_tt_find_safe_dismiss`: матчит «Не сейчас»/«Закрыть»/«Не разрешать» на реальных и синтетических дампах; **НЕ** матчит «Продолжить»/«Разрешить»/«Подписаться»/«Открыть настройки».
- `_tt_read_login_confirm_banner`: извлекает handle из баннера; `None` на профиле/ленте без баннера.
- `_tt_screen_is_transitional`: True на дампе со шторкой+спиннером, False на чистом профиле/ленте.
- Интеграция `_tt_handle_post_switch_unknown`: по фикстуре каждого под-режима (A/B/C) → recovered/mismatch согласно сценарию; happy-path (чистый профиль target) не регрессирует.
- Регрессия: полный switcher-suite зелёный.

### Live smoke + soak

- Post-deploy: re-queue 9124/7715 (+ при возможности 8573 под-режим B) → switcher проходит, в логах новые события confirm/dismiss.
- 24h soak: тренд `tt_post_switch_verify_unrecoverable` 1–3/сутки → ~0 в части модалок/переходов. Остаток вне scope (см. §7) → отдельные WP по новым `tt_post_switch_blocked_no_safe_button`.

---

## 7. Вне scope

- **Foreground-drift** (TikTok ушёл в другое приложение/launcher) — WP #130.
- **Picker тапает не тот ряд** (открылся чужой профиль после dismiss) — отдельный picker-баг.
- **Mismatch-путь** (cold-restart re-pick) — не трогаем.
- **Genuine account-block** через security-флоу: модалку «Быстрая проверка безопасности» закрываем (как делает текущий `_tt_dismiss_security_prompt`); если TikTok после закрытия снова требует верификацию — это территория `account_blocks` (WP #93-паттерн), вне этого фикса.

---

## 8. Артефакты

- Spec: `docs/superpowers/specs/2026-05-22-tt-post-switch-modal-agnostic-confirm-design.md` (этот файл)
- Входной триаж: `docs/evidence/2026-05-19-tt-fails-triage.md`, `docs/evidence/2026-05-22-tt-publish-fails-triage.md`
- Кадры разбора: `/tmp/wp67-frames/sheet_{9124,8573,7715}.jpg`
- Код: `account_switcher.py` — `_tt_handle_post_switch_unknown` (4797), `_post_switch_verify_handle` (4663), `_navigate_to_profile_tab` (4746), `_is_tt_feed_after_pick` (4721), pick→verify loop (~2760–2899)
