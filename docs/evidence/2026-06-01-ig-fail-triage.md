# IG publish-fail триаж — 2026-06-01

Источник: `publish_tasks` (openclaw, localhost:5432), `platform='Instagram'`, окно 7 дней.

## Ранжирование падений (status='failed', 7д / 3д)

| # | error_code | 7д | 3д | Реальная причина (логи/скринкасты) | Статус |
|---|---|---|---|---|---|
| 1 | watchdog_subprocess_hang | 476 | 1 | Инфра-хэнг процесса (инцидент 27.05) | WP#165, ~0 сейчас |
| 2 | ig_account_switcher_wrong_foreground | 121 | 15 | Свитчер ловил чужой fg | WP#197 шипнут 01.06 |
| 3 | ig_share_tap_no_progress | 98 | 2 | false-negative Share | WP#181 Готово |
| 4 | **switch_failed_unspecified** | **68** | **58 ↑** | **ADB-preflight: adb_devices_unreachable(43)/adb_device_not_ready(15) → catch-all → unknown → transient → auto-retry** | WP#199 / WP#207 |
| 5 | ig_caption_screen_not_reached | 34 | 5 | Интерстишалы редактора Reels | WP#193 Тестирование |
| 6 | process_interrupted | 25 | 14 | Процесс убит извне (инфра) | — |
| 7 | ig_target_not_in_picker | 20 | 6 | Аккаунт не залогинен на девайсе (длинный хвост, 18 акк.) | WP#102 ops |
| 8 | ig_editor_falsely_detected_as_gallery | 15 | 5 | Редактор ложно=галерея | WP#206 шипнут 01.06 |
| 9 | date_mismatch | 14 | 2 | minute-rounding false-positive | WP#76 Готово |
| 10 | ig_upload_confirmation_timeout | 8 | 3 | upload-спиннер виснет ~5мин → timeout | открыт, малый объём |

## Главный вывод

Доминирующий живой драйвер IG-падений = `switch_failed_unspecified` (58/3д, растёт). Это **не баг публикатора**, а недоступность девайсов по ADB на preflight, замаскированная под catch-all код свитчера.

Доказательство (все 58 за 3д):
- Логи — двухстрочные, обрыв на preflight: `ADB preflight: adb_devices_unreachable` (43) / `adb_device_not_ready` (15).
- Ни один лог не содержит слова «switch». Скринкастов нет (rec=0) — до экрана дело не доходит.
- `error_class=unknown` у всех 58.

## Два вреда (разделение скоупа)

1. **Мисклассификация (labeling)** — финальный `error_code` = `switch_failed_unspecified` вместо реальной preflight-причины.
   → Покрыто **WP#199** (follow-up классификатора) и **WP#207** (ordering-баг `publisher_base.py:4307-4308`: `update_status` до `log_event` → дефолт `unknown`; фикс=swap; + выявлен SPOF-шлюз 147.45.251.85, 237 фейлов/флот).

2. **Поведение (retry-churn)** — задачи на офлайн-девайсе классятся `transient_within_limits` и **авто-ретраятся**.
   - 58 фейлов за 3д = **всего 21 уникальная задача публикации** (client_publish_id).
   - Среднее **2.76 ретрая/задачу, макс 5**.
   - 44/58 несут `transient_within_limits` в events.
   → **НЕ покрыто** ни #199, ни #207 → новая WP (этот триаж).

WP#195 (device-health gate) проверяет здоровье девайса на спавне, но девайс флапает уже после гейта (часто через SPOF-шлюз) → задача всё равно спавнится и жжёт ретраи.

## Предложение фикса (новая WP)

Preflight `adb_devices_unreachable` / `adb_device_not_ready` → НЕ классифицировать как `transient_within_limits` (авто-ретрай), а:
- маршрутизировать в device-health-hold (связка с гейтом WP#195), либо
- ограничить ретраи device-health-причин (cooldown/backoff per device_serial), а не общим transient-лимитом.

Kill-switch обязателен. Связанные: WP#199 (labeling), WP#207 (ordering+SPOF), WP#195 (spawn-gate), WP#99 (ops re-auth RF8YA0V7LEH).
