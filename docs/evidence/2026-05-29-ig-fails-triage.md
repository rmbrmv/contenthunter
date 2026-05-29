# IG publish-fails triage — 2026-05-29

Окно: `publish_tasks`, `platform ILIKE 'instagram'`, `status='failed'`, `testbench=false`.
Группировка по **последней** `meta.category` события типа `error` (т.к. `error_code` пишет ПЕРВУЮ ошибку и врёт).

## Объёмы за 14 дней (сырьё)

| причина (last error category) | 14д |
|---|---|
| watchdog_subprocess_hang | 479 |
| ig_share_tap_no_progress | 112 |
| ig_account_switcher_wrong_foreground | 100 |
| ig_caption_screen_not_reached | 46 |
| ig_target_not_in_picker | 35 |
| process_interrupted | 19 |
| ig_editor_falsely_detected_as_gallery | 13 |
| ig_upload_confirmation_timeout | 12 |
| ... хвост | <12 |

Всего IG `failed` 14д = 919 (+ 460 `published_no_url`).

## Очистка от шума

- **watchdog_subprocess_hang = 474 из 479 в один день 26.05** → разовый инфра-инцидент (WP#165, circuit-breaker отгружен). Не IG-флоу-баг.
- **process_interrupted** = PM2 deploy-kill (шум), исключаем.
- **ig_account_switcher_wrong_foreground**: 88 из 100 тоже 26.05 (тот же спайк).

### Чистый рейтинг IG-флоу-багов (7д, без 26.05 + без шума)

| причина | 7д |
|---|---|
| ig_share_tap_no_progress | 75 |
| **ig_caption_screen_not_reached** | **28** |
| ig_target_not_in_picker | 20 |
| ig_editor_falsely_detected_as_gallery | 13 |
| ig_account_switcher_wrong_foreground | 12 |

## #1 по объёму — ig_share_tap_no_progress (75/7д): УЖЕ ЗАКРЫТ как false-negative

WP#181 (OpenProject «Готово»): root = false-negative от stale uiautomator + long transit.
Скринкасты подтвердили:
- **task 11711** (@virtual.card.pro, 28.05): Share нажат, детект «застрял в редакторе» + 3 ретапа → `ig_share_tap_no_progress`, НО финальные кадры = лента Reels с контентом «ПОДТВЕРЖДАЕМ / Онлайн-оплата стала проще» → **пост опубликован**.
- **task 11632** (@SPlus_Servicess, 28.05): тот же паттерн + интерстициальный диалог «Reels … Поделиться»; финал = лента с контентом splus_auto → **опубликован**.

⚠️ Замечание: #181 «Готово», но эти задачи всё ещё `status='failed'` + handoff в ручную (post-mortem probe их не реклассифицировал в success). Возможен недочёт покрытия probe — кандидат на ре-верификацию #181 отдельно.

## ВЫБРАН ДЛЯ ФИКСА — ig_caption_screen_not_reached (28/7д, стабильно каждый день)

Самый крупный **настоящий неадресованный** IG-фейл. Каждый день 5–9 шт (25.05:5, 26:7, 27:9, 28:7, 29:5).

Терминальные сообщения (10д, 43 шт):
- 14× `Instagram: caption_input не найден на экране — abort без adb_text`
- 15× транзиентный авто-перезапуск
- 14× handoff в ручную

### Механика (из events task 12027)
`редактор Reels` → `экран подписи найден (шаг 1)` → `caption_input_text_view не найден в XML` → `caption_input не найден на экране — abort без adb_text`.
Т.е. редактор открыт, но поле подписи (EditText) отсутствует в UI-дампе → честный abort (защита WP#81, root cause был забэклоен).

### Root cause из скринкастов — семейство интерстициальных оверлеев НОВОГО редактора Reels
- **task 12027** (@SPlus_Servicess, 29.05): полноэкранная промо-модалка «**Запечатлейте момент с новой кнопкой камеры**» (Открыть настройки устройства / Не сейчас) + туториал-оверлей редактора «**Проведите по экрану вверх или вниз, чтобы установить размер для режима предпросмотра**».
- **task 11893** (@SPlus.Pro, 29.05): промо «**Сделайте свои видео лучше с помощью Edits**» → уводит в **Google Play (Edits: Видеомейкер)** + тот же swipe-туториал.

Оверлеи всплывают ПОСЛЕ выбора видео, на этапе редактор→подпись, и перекрывают EditText.

### Почему не дубль закрытых WP
- **WP#61 (Готово)**: баннер «Edits» — но на этапе **пикера видео** (`ig_picker_wrong_candidate`). Здесь — этап **редактора**.
- **WP#81 (Готово)**: caption fill — другой механизм (IME не открывается / теряется фокус). Здесь EditText вообще отсутствует в дереве из-за оверлея.

### Предлагаемый фикс
Расширить dismiss-вайтлист на этапе редактора/подписи на новые интерстициалы:
«Запечатлейте момент с новой кнопкой камеры» (тап «Не сейчас»), «Edits» промо (dismiss, не уходить в Google Play), preview-size swipe-туториал (тап мимо/Готово). Под kill-switch. Перед слепым abort — пробовать dismiss + повторный дамп.

## Артефакты
- Скринкасты: task11711, task11632, task12027, task11893 (save.gengo.io/autowarm/screenrecords/instagram/).
- UI-дампы: save.gengo.io/autowarm/ui_dumps/instagram/.

## Исход (29.05)

### WP#181 (ig_share_tap_no_progress) — ВЕРИФИЦИРОВАН PASS
Post-mortem probe активен в прод с ночи 28→29.05 (~04:52). После активации **0**
no_progress-фейлов; 5 реклассификаций `ig_share_postmortem_success` → post_url
захвачен. Все 123 «фейла» в БД предшествовали активации (≤28.05 12:11). #181
оставлен «Готово» + verify-комментарий.

### WP#193 (ig_caption_screen_not_reached) — SHIPPED+DEPLOYED 29.05
Фикс `_dismiss_ig_editor_interstitials` (publisher_instagram.py): ladder перед
abort в `_fill_instagram_caption_and_publish` — промо «новой кнопкой камеры»→«Не
сейчас»; Edits-промо→WP#61 `_dismiss_ig_edits_promo`; coach-mark→recovery-focus.
Kill-switch `IG_CAPTION_INTERSTITIAL_DISMISS_ENABLED` (default on). 12 unit-тестов,
369 passed (1 pre-existing fail camera_recovery не связан), codex 0 P1/P2.
PR #126 → merged main `f4d3bb3`; прод `/root/.openclaw/workspace-genri/autowarm`
FF-pull → f4d3bb3 (HEAD==origin/main, синтаксис OK, server.js не менялся →
PM2-restart не нужен). OP#193 → «Тестирование». Verify: утренняя пачка — рост
`ig_camera_button_promo_dismissed`/`ig_edits_promo_dismissed`, падение
`ig_caption_screen_not_reached`.
