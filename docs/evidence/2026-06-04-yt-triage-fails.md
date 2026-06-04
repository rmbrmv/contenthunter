# YT fail-триаж 2026-06-04

Платформа: **YouTube**. БД: `postgresql://openclaw@localhost:5432/openclaw`, таблица `publish_tasks`.
Снято ~05:00 МСК 04.06 (день только начался → за «сегодня» всего 2 падения; для объёма взято окно 72ч).

## Сводка падений

### «Сегодня» (04.06, до ~05:00 МСК) — status=failed
| id | error_code | error_class | account |
|----|-----------|-------------|---------|
| 15208 | yt_editor_not_reached | ui_changed | irbis.academy |
| 15187 | yt_post_switch_app_not_foregrounded | ui_changed | DubaiHomes-est |

Всего 2 — несопоставимо мало для приоритизации, поэтому расширил окно.

### Окно 72ч — реальные падения по error_code (исключён артефакт рестарта)
| error_code | class | count | примечание |
|-----------|-------|------:|-----------|
| switch_failed_unspecified | unknown | 114 | 113 из них в один день 01.06 — ADB/preflight аутэйдж, покрыт WP#195/#207/#210 |
| adb_device_not_ready | device_unreachable | 46 | 37 — 02.06, device-health, покрыт WP#195/#210/#220 |
| **yt_picker_target_absent** | **ui_changed** | **8** | **лидер среди реальных UI-багов; повторяется ежедневно на одних аккаунтах** |
| channel_deleted | banned | 3 | покрыт WP#180/#200 |
| yt_app_not_foregrounded | ui_changed | 2 | |
| yt_accounts_btn_missing_postmortem | unknown | 2 | один тестовый проект (Ivana-o3j / Тестовый проект) |
| yt_editor_not_reached | ui_changed | 2 | WP#192 (launcher-drift) — возможный рецидив |
| прочие (по 1) | — | 7 | yt_picker_dismissed, yt_target_not_in_picker_after_scroll, yt_editor_upload_timeout, yt_post_switch_app_not_foregrounded, critical_exception, timeout |
| process_interrupted | (null) | 13 | **АРТЕФАКТ**: все `KeyboardInterrupt` в одну секунду (~10:44:37 03.06) — единый рестарт/SIGINT убил бегущие задачи; не баг публикации |

## Артефакт process_interrupted (исключён)

Три примера (15035/15036/15039) завершились строкой `run_publish_task interrupted: KeyboardInterrupt:`,
все `updated_at` ≈ 10:44:37–43 03.06 — синхронный обрыв = рестарт процесса, не сбой флоу.

## Выбранный для фикса баг: yt_picker_target_absent (ложный)

**8 падений за 72ч**, повторяется день в день на одних аккаунтах:
`enoty-po-polkam-poker` ×3 (01/02/03.06), `payworldcards` ×2, `virtualcardpro` ×2, `septic.master` ×1.

### Доказательство — task 15034 (enoty-po-polkam-poker, 03.06)
Лог: `FAIL: ... аккаунт 'enoty-po-polkam-poker' не привязан к устройству (шаг=yt_4_pick_account)`.

Скринкаст (`task15034_fail_screenrec_15034_*.mp4`, кадр ~262с): **пикер аккаунтов открыт, целевой аккаунт ПРИСУТСТВУЕТ** в секции «Другие аккаунты»:
- gmail `enoty.po.polkam.poker@gmail.com` → канал **«Enoty po polkam poker26»** (3 подписчика).

То есть аккаунт залогинен и виден, но матчер отрапортовал «не привязан». Рядом — почти идентичный sibling «Enoty po polkam school» (выбран сейчас).

### Корневая причина (две накладывающиеся)

`account_switcher.py` цепочка матча в `_find_and_tap_account`:
1. **gmail-hint** (`find_yt_row_by_gmail`) — у `enoty-po-polkam-poker` в `factory_inst_accounts.gmail` записан
   `lenoty.po.polkam.poker@gmail.com` (**лишняя «l» в начале** — опечатка в данных), а на экране `enoty.po.polkam.poker@gmail.com`.
   Поиск по подстроке `lenoty…` в `enoty…` → промах. (У `payworldcards`/`virtualcardpro` gmail пуст → путь недоступен.)
2. **channel-name fallback** (`find_yt_channel_name_matches`, строки ~1228–1232): правило
   ```
   cn == tn  ИЛИ  (|len(cn)-len(tn)| == 1 И один префикс другого)
   ```
   - target `enoty-po-polkam-poker` → `_alnum_norm` = `enotypopolkampoker` (18)
   - канал «Enoty po polkam poker26» → `enotypopolkampoker26` (20)
   - не равны; разница длин = **2** (числовой суффикс «26»), а допускается лишь **1** (кейс relisme+e из WP#66)
   - → матч не срабатывает → scroll исчерпан → `yt_picker_target_absent` → ложный фейл.

Правило WP#66 (OpenProject #66) рассчитано на 1-символьную уникализацию хэндла, но реальные YT-каналы
получают **многосимвольные числовые суффиксы** (`…poker` → «…poker26»). Это регресс/недоохват #66.

### Предлагаемый фикс (для последующей TDD-реализации, не в этой сессии)
- Расширить толерантность `find_yt_channel_name_matches`: разрешать, что нормализованный канал = target + **числовой суффикс** (`^{tn}\d+$`), при сохранении guard «тапаем только при единственном совпадении» (sibling «school» не числовой суффикс → не коллидирует).
- Параллельно — ops/data-фикс опечатки gmail у `enoty-po-polkam-poker` (`lenoty…`→`enoty…`) и бэкфилл пустых gmail для затронутых аккаунтов.
- Kill-switch на расширенное правило.

### Отличие от существующих задач
- **OP#202** — ops: на устройстве RFGYA19DB8K реально сменились Google-аккаунты (назначенных нет в пикере). Здесь обратное: аккаунт ЕСТЬ, матчер промахивается → код-баг.
- **OP#66** — исходный channel-name-match (relisme); эта задача расширяет его правило.
