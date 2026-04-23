# Farming Testbench — Phone #171 Accounts Discovery (T1)

**Date:** 2026-04-23
**Method:** `account_revision.py` (thin wrapper over `AccountSwitcher.read_accounts_list`)
**Device:** RF8Y90GCWWL (phone #171, raspberry #8, ADB 82.115.54.26:15088)

## Источник

- IG: частично от пользователя (2 аккаунта), подтверждены revision
- TT/YT: ADB-автообнаружение (user попросил проверить самостоятельно)

## Обнаруженные аккаунты

### Instagram — ✅ ВНЕСЕНЫ в factory_inst_accounts в ходе T1

| id   | username            | pack          | pack_name              | active | источник          |
|------|---------------------|---------------|------------------------|--------|-------------------|
| 1685 | `ivana.world.class` | 308 (171a)    | Тестовый проект_171a   | ✅     | user + revision   |
| 1686 | `born.trip90`       | 309 (171b)    | Тестовый проект_171b   | ✅     | user + revision   |

*Распределение по пакам сделано `account_revision.py` автоматически (правило: один аккаунт на платформу в паке).*

### TikTok — ❌ НЕ ПРИГОДЕН (не залогинен / stuck в чужом профиле)

- Экран profile показывает `@odobren.kz`, но XML-анализ дампа подтверждает: это **чужой профиль**, не собственный:
  - Видны кнопки «Подписаться» (bounds `[134,728][472,852]`) и «Сообщение» (`[472,728][810,852]`)
  - На собственном профиле TikTok показывает «Редактировать профиль» и «Поделиться» — их в дампе нет
- Это известный баг #171: TT stuck in foreign profile. Прошлая memory упоминала `@rahat.mobile.agncy.31` — сейчас `@odobren.kz`, природа та же.
- **Блокер:** нужен ручной логин правильного TT-аккаунта (через UI на устройстве) либо скрипт восстановления логина.
- **До восстановления — TT исключён из farming-testbench scope.**

### YouTube — ❌ НЕ ПРИГОДЕН (Google-аккаунты без каналов)

- Через альтернативный путь `am start com.google.android.youtube/.app.application.Shell_SettingsActivity` → «Аккаунт» → «Смена или настройка аккаунта» успешно открыл account-switcher:
- **Google-аккаунты на устройстве:**
  - `born.trip90@gmail.com` → display name "Born" → **«Нет канала»**
  - `ivana.world.class@gmail.com` → display name "Ivana" → **«Нет канала»**
- Оба gmail'а залогинены в YouTube, но YT-каналы у них не созданы. Это объясняет почему bottom-nav profile не открывает список — показывать нечего.
- Для farming-testbench (watch/like/subscribe) каналы не обязательны, но для полного warm-цикла (публикация Shorts) — нужны. Решение за user'ом.
- **Блокер до решения:** либо создать YT-каналы для обоих gmail'ов (ручное действие), либо исключить YT из scope MVP.

## Summary по T1 (финал)

После ручного вмешательства пользователя (2026-04-23): TT залогинен в правильные own-аккаунты, YT-каналы созданы для обоих gmail'ов. Аккаунты добавлены через UI-редактор паков.

### Финальное состояние factory_inst_accounts для phone #171

| pack       | platform  | username           | id   | active |
|------------|-----------|--------------------|------|--------|
| **171a** (308) | instagram | `ivana.world.class` | 1685 | ✅ |
| **171a** (308) | tiktok    | `user899847418`     | 1690 | ✅ |
| **171a** (308) | youtube   | `Ivana-o3j`         | 1691 | ✅ |
| **171b** (309) | instagram | `born.trip90`       | 1686 | ✅ |
| **171b** (309) | tiktok    | `born7499`          | 1692 | ✅ |
| **171b** (309) | youtube   | `Born-i6i3n`        | 1693 | ✅ |

**Пригодны для farming-testbench:** все 6 аккаунтов на всех 3 платформах. MVP farming orchestrator может round-robin'ить IG × TT × YT.

### Поправка к плану

- T2 больше **не** должен делать INSERT в factory_inst_accounts — аккаунты уже внесены. T2 сужается до миграции только `autowarm_tasks.testbench` колонки.
- Smoke-preflight (T3) остаётся — нужно подтвердить что при запуске TT/YT на #171 попадает в own-profile state (не чужой профиль).

## Открытые вопросы к пользователю

1. **TikTok**: own-аккаунт не залогинен, TT stuck в чужом профиле. Нужно решение:
   - (A) ручной логин TT-аккаунта (user заходит через UI/Vysor и логинится)
   - (B) скрипт восстановления (pm clear com.zhiliaoapp.musically + свежий логин по credentials — если credentials есть в secrets)
   - (C) исключить TT из farming-testbench scope MVP — включить позже
2. **YouTube**: у обоих gmail'ов нет каналов. Решение:
   - (A) создать YT-каналы вручную для born.trip90 и ivana.world.class (user действие через UI)
   - (B) исключить YT из farming-testbench scope MVP — включить после создания каналов
   - (C) разрешить farming без channel (только watch/like/subscribe без публикации) — требует доработки warmer.py

## Surface-факты (для будущих сессий)

- Phone #171 = raspberry **#8** (не #7 как было в memory до 2026-04-23)
- Device serial: `RF8Y90GCWWL`, model: `SM-A175F` (Samsung A17)
- Dumps/logs лежат в `/tmp/autowarm_revision_dumps/` и `/tmp/revision-171-discovery.log`
- Full revision JSON: `/tmp/revision-171-discovery.json`

## Dumps (ссылки на XML)

```
/tmp/autowarm_revision_dumps/switch_revision-RF8Y90GCWWL-1776949712_ro_5_dropdown_tiktok_1776950028.xml
/tmp/autowarm_revision_dumps/switch_revision-RF8Y90GCWWL-1776950031_ro_3_profile_youtube_1776950100.xml
```
