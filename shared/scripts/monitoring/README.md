# System Monitoring

## Компоненты

### 1. Resource Monitor (`check_resources.py`)
Проверяет использование ресурсов и отправляет алерты при превышении порогов.

**Пороги:**
- Диск: 80%
- RAM: 85%
- CPU: 90% (load average 15min)

**Использование:**
```bash
# Проверка с выводом
python3 check_resources.py --verbose

# Тихий режим (только алерты)
python3 check_resources.py
```

**Логи алертов:**
- `/root/.openclaw/workspace/logs/resource_alerts.log`

**Cron:**
- Каждый час: `0 * * * *`

---

### 2. Temp Cleanup (`cleanup_tmp.sh`)
Удаляет старые файлы из /tmp/

**Использование:**
```bash
# Удалить файлы старше 7 дней (по умолчанию)
./cleanup_tmp.sh

# Удалить файлы старше 3 дней
./cleanup_tmp.sh 3
```

**Логи:**
- `/root/.openclaw/workspace/logs/cleanup.log`

**Cron:**
- Ежедневно в 3:00: `0 3 * * *`

---

### 3. Swap
- **Размер:** 2 GB
- **Файл:** `/swapfile`
- **Автозагрузка:** Да (в /etc/fstab)

**Проверка:**
```bash
free -h
swapon --show
```

---

## Установка

Всё уже настроено автоматически:
- ✅ Swap 2GB создан и активирован
- ✅ Cron jobs добавлены
- ✅ psutil установлен
- ✅ Логи настроены

## Мониторинг

### Текущий статус
```bash
python3 check_resources.py --verbose
```

### Просмотр алертов
```bash
tail -f /root/.openclaw/workspace/logs/resource_alerts.log
```

### Просмотр очистки
```bash
tail -f /root/.openclaw/workspace/logs/cleanup.log
```

### Cron статус
```bash
crontab -l
```

---

## TODO (опционально)

- [ ] Интеграция с Telegram (отправка алертов в чат)
- [ ] Мониторинг размера PostgreSQL
- [ ] Мониторинг Docker контейнеров
- [ ] Grafana + Prometheus для графиков
