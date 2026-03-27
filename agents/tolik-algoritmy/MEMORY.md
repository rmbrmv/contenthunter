# MEMORY.md — Нурия's Long-Term Memory

## Идентичность
- **Имя:** Нурия
- **Роль:** Фармер аккаунтов в ContentHunter
- **Характер:** Методичная, осторожная, внимательна к деталям
- **Язык:** Русский, краткая речь

## Главная цепочка работы
```
Саша (регистрация) → Нурия (прогрев) → Альфия (выкладка)
```

## Инструменты
- **warmer.py** — основной скрипт прогрева (путь: `/root/.openclaw/workspace-genri/autowarm/warmer.py`)
  - Вызов: `python3 warmer.py <task_id>`
  - Данные берёт из БД (autowarm_tasks), не из флагов
- **ADB Relay:** `147.45.251.85` (remote server для управления устройствами)
- **DB локальная:** localhost 5432, пользователь openclaw, БД openclaw
- **DB factory (readonly):** 193.124.112.222:49002, пользователь roman_ai_readonly

## Таблицы БД
- `autowarm_tasks` — задачи прогрева (device_serial, account, protocol_id, current_day, status)
- `autowarm_protocols` — протоколы (id, platform, name, days_config)
- `autowarm_day_logs` — логи по дням
- Factory DB: `device_numbers`, `raspberry_port` — связь serial → ADB port

## Контакты агентов
- **Генри** (label: `genri`) — дает задачи, принимает отчеты
- **Альфия** (label: `alfiya`) — берет готовые аккаунты после прогрева
- **Саша** (label: `sasha`) — регистрирует аккаунты

## Критические уроки
1. **На /start:** Прочитай SOUL.md ДО первого ответа, не после
2. **Перед использованием скрипта:** Посмотри исходный код/README
3. **Длительные операции:** Background процесс (`&`), потом `process(action=poll)`
4. **Отчеты Генри:** JSON + краткое описание (как Нурия говорит)

## Текущие задачи
- Task #99: прогрев @test_account на Instagram, RF8Y91F8EJH
  - db_task_id: 8
  - status: **CANCELLED** (2026-03-18 21:15 — Генри отменил после напоминания)
  - День 1: ✅ завершён (31 видео, 1 лайк)
  - День 2: ❌ отказ в 2026-03-03 08:44:34
  - ✅ Закрыта. Ожидаю новую задачу от Генри.
  
## Критические уроки (обновлено 2026-03-09)
1. **На /start:** Прочитай SOUL.md ДО первого ответа, не после
2. **Перед использованием скрипта:** Посмотри исходный код/README
3. **Длительные операции:** Background процесс (`&`), потом `process(action=poll)`
4. **Отчеты Генри:** JSON + краткое описание (как Нурия говорит)
5. **Мониторинг между днями:** Даже в background процессе, проверяй статус в БД регулярно. День 1 ≠ день 2!
6. **Проактивность при блоке:** Заблокированная задача (status=failed, hung, pending >24ч) требует инициативы. Отчитаться без запроса.
7. **🆕 Отчет ≠ решение:** После сообщения о проблеме либо восстанавливаешь задачу, либо ждёшь ответа Генри, но не молчишь несколько дней.


---

## AutoWarm — adb_utils.py + ADBKeyBoard (2026-03-20)

Создан общий модуль **`autowarm/adb_utils.py`**:
- `ensure_adbkeyboard(serial, port, host)` — проверяет/устанавливает ADBKeyBoard, активирует IME. Вызывается в `publisher.py` (`run()`) и `warmer.py` (`initialize()`)
- `adb_text(serial, port, host, text)` — ADBKeyBoard → clipboard → ASCII fallback
- APK: `apks/ADBKeyboard.apk` v2.4-dev

Фикс TikTok (задача #254): описание не вводилось из-за `clickable_only=True` — исправлено на `clickable_only=False` + fallback `(540,290)`.

**Коммит:** `ae7f479` в `GenGo2/delivery-contenthunter`
