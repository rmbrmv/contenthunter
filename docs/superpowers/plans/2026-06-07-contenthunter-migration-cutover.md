# Переезд ContentHunter — Фаза 1–2: окно переезда и переключение

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Перенести боевой ContentHunter на новый сервер с минимальным простоем: поднять прод-стенды, перелить реальные данные, переключить домены, не потеряв данные и не сломав публикацию.

**Предусловие:** Фаза 0 завершена (тест-стенды живые, авто-деплой работает, отвязка от схемы `factory` сделана, дамп-стратегия и обезличивание отработаны на тесте). Все код-фиксы — в ветках `develop` обоих репозиториев.

**Архитектура цели:** на NEW (`46.225.145.245`) поднимаются `prod-delivery` (:3848, ветка `main`, БД `contenthunter`) и `prod-client` (:8000, `main`, `contenthunter`). Старые домены `client/delivery.contenthunter.ru` (на OLD `72.56.107.157`) 301-редиректят на `prod-client/prod-delivery.contenthunter.ru`.

**Ключевой принцип безопасности публикации:** прод-стенд delivery стартует СНАЧАЛА с `TEST_MODE=1` (фоновые задания, включая публикацию, выключены) для смоука на реальных данных; публикация включается ОТДЕЛЬНЫМ шагом (снятие `TEST_MODE`) уже после проверки.

---

## Решения, которые надо подтвердить до старта

1. **Время окна.** Данил подтвердил «сейчас активности нет». Окно ~1–2 часа. Согласовать конкретный старт.
2. **Канонический домен.** После переезда основной адрес = `prod-client`/`prod-delivery.contenthunter.ru`; старые `client`/`delivery` → 301 на них. (Подтверждено ранее.)
3. **Контролируемый старт публикации.** Прод стартует с `TEST_MODE=1`; публикация включается вручную после смоука. (Рекомендация — встроена в план.)
4. **OLD не выключаем целиком** — на нём остаются другие продукты (systematika, hr, analytics и т.д.). Гасим только CH-сервисы и вешаем редирект CH-доменов.
5. **Унификация тест-паролей** (опционально, вне окна): привести test-delivery к тому же паролю — не блокер.

---

### Task 1: Промоушен кода develop→main (вне окна, без простоя)

**Files:** PR в обоих репозиториях.

- [ ] **Step 1: PR develop→main, delivery**

```bash
gh pr create --repo GenGo2/delivery-contenthunter --base main --head develop \
  --title "Релиз: переезд на новый сервер (env-креды, public-схема, device_state, TEST_MODE)" \
  --body "Промоушен проверенных на тесте изменений в main для прод-деплоя."
```
Просмотреть дифф (живое review), смёржить (`--merge`, без squash, чтобы сохранить историю). Аналогично client.

- [ ] **Step 2: PR develop→main, validator**

```bash
gh pr create --repo GenGo2/validator-contenthunter --base main --head develop \
  --title "Релиз: переезд (requirements, alembic env, DATABASE_URL из env)" --body "Промоушен."
```
Смёржить после ревью.

Expected: `main` обоих репо = `develop` (содержит все фиксы переезда).

---

### Task 2: Поднять прод-стенды на NEW (вне окна, без простоя)

**Files:** `/opt/contenthunter/{prod-delivery,prod-client}` + `.env` + `/opt/contenthunter/ecosystem.prod.config.js` на NEW.

- [ ] **Step 1: Клонировать прод-стенды из main (через SSH-deploy-remote)**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  cd /opt/contenthunter
  rm -rf prod-delivery prod-client
  git clone -b main github-delivery:GenGo2/delivery-contenthunter.git prod-delivery
  git clone -b main github-validator:GenGo2/validator-contenthunter.git prod-client
  cd prod-delivery && git log -1 --oneline; cd ../prod-client && git log -1 --oneline
'
```
(SSH-алиасы `github-delivery`/`github-validator` уже настроены в `/root/.ssh/config` на NEW из Фазы 0.)

- [ ] **Step 2: `.env` прод-стендов (реальные значения с OLD + прод-оверрайды)**

**prod-delivery `/opt/contenthunter/prod-delivery/.env`:** копия боевого delivery `.env` с OLD (`sudo cat /root/.openclaw/workspace-genri/autowarm/.env`), оверрайды: `PGHOST=localhost PGPORT=5432 PGDATABASE=contenthunter PGUSER=contenthunter PGPASSWORD=<из /opt/contenthunter/_ops/db/db.env>`, `PORT=3848`, **`TEST_MODE=1`** (временно, снимем после смоука), `DAILY_REPORT_ENABLED=1` (как на проде, но см. примечание — на время окна можно 0). Права 600.

**prod-client `/opt/contenthunter/prod-client/backend/.env`:** копия боевого validator backend `.env`, оверрайды: `DATABASE_URL=postgresql+asyncpg://contenthunter:<PW>@localhost:5432/contenthunter`, `ALEMBIC_DATABASE_URL` аналогично, `BACKEND_PORT=8000`, удалить мёртвые `FACTORY_DB_*`. Права 600.

- [ ] **Step 3: Зависимости**

```bash
ssh ... root@NEW '
  cd /opt/contenthunter/prod-delivery && npm ci
  cd /opt/contenthunter/prod-client/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  cd /opt/contenthunter/prod-client/frontend && npm ci && npx vite build
  # unic-worker (на проде НУЖЕН — он публикует уникализацию)
  cd /opt/contenthunter/prod-delivery/unic-worker && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
'
```

- [ ] **Step 4: PM2 ecosystem прод**

Создать `/opt/contenthunter/ecosystem.prod.config.js`: процессы `prod-delivery` (server.js, cwd prod-delivery), `prod-delivery-unic` (unic-worker/.venv python worker.py), `prod-client` (uvicorn src.main:app --port 8000). НЕ запускать пока (данных в БД `contenthunter` ещё нет — стартуем в Task 5).

---

### Task 3: Старт окна — плашка «технические работы» на OLD

**Files:** OLD Caddy — отдельный сниппет техработ; `/var/www/maintenance/index.html`.

- [ ] **Step 1: Страница техработ**

Создать `/var/www/maintenance/index.html` (статичная, «Идут технические работы по переезду, скоро вернёмся»).

- [ ] **Step 2: Caddy OLD — отдать 503 на client/delivery, кроме IP Данила**

В `/etc/caddy/Caddyfile` на OLD для блоков `client.contenthunter.ru` и `delivery.contenthunter.ru` обернуть:
```caddy
client.contenthunter.ru {
    @allowed remote_ip <IP_ДАНИЛА> <IP_CLAUDE>
    handle @allowed { reverse_proxy localhost:8000 }   # как было — для нас доступ остаётся
    handle {
        handle_path /* { root * /var/www/maintenance; rewrite * /index.html; file_server }
        respond 503
    }
}
```
(Аналогично delivery → localhost:3848.) Узнать IP Данила заранее. `caddy validate && systemctl reload caddy`.

Expected: обычные пользователи видят плашку (503), Данил/Claude — рабочий интерфейс OLD.

---

### Task 4: Заморозка писателей БД на OLD

- [ ] **Step 1: Остановить процессы-писатели**

```bash
sudo pm2 stop 35 36 33 26 28 29   # autowarm, unic-worker, testbench, farming-*
sudo pm2 list
```

- [ ] **Step 2: Отключить cron, пишущий в БД**

```bash
sudo crontab -l > /root/crontab.backup.cutover && sudo crontab -r   # или закомментировать строки CH
```
(Сверить содержимое; вернуть после, если есть не-CH задачи. На OLD основной crontab root — проверить, что там CH-задачи.)

- [ ] **Step 3: Зафиксировать «точку отсчёта»** — запомнить max(updated_at)/счётчики ключевых таблиц для последующей сверки.

```bash
sudo docker exec openclaw-postgres psql -U openclaw -d openclaw -c "SELECT 'publish_queue', count(*) FROM publish_queue UNION ALL SELECT 'publish_tasks', count(*) FROM publish_tasks UNION ALL SELECT 'validator_content', count(*) FROM validator_content;"
```

Expected: на OLD больше никто не пишет в `openclaw`.

---

### Task 5: Финальный дамп → restore в прод-БД + старт прод (в окне)

- [ ] **Step 1: Выборочный дамп реальных данных (тот же дроп-лист, что на тесте)**

```bash
# DROP-list (75 чужих+ничейных) — из Task 10 Фазы 0. Сгенерировать -T public."<table>" для каждой.
sudo docker exec openclaw-postgres pg_dump -U openclaw -d openclaw --schema=public --no-owner --no-privileges $TARGS -Fc > /tmp/ch_prod.dump
ls -lh /tmp/ch_prod.dump
```

- [ ] **Step 2: Перенести и восстановить в `contenthunter` (прод-БД, БЕЗ обезличивания)**

```bash
scp -i /home/claude-user/.ssh/cpx62_key /tmp/ch_prod.dump root@46.225.145.245:/tmp/
ssh ... root@NEW 'docker cp /tmp/ch_prod.dump contenthunter-postgres:/tmp/ && cd /opt/contenthunter/_ops/db && docker compose exec -T postgres pg_restore --no-owner --role=contenthunter -d contenthunter /tmp/ch_prod.dump 2>&1 | tail -30'
```
Изучить вывод (ожидаемое предупреждение про вью device_state, которого нет — норм).

- [ ] **Step 3: factory_hashtags + device_state view в проде**

```bash
# factory_hashtags (как на тесте — копия из factory.hashtags)
sudo docker exec openclaw-postgres pg_dump -U openclaw -d openclaw -t factory.hashtags --no-owner -Fp | sed 's/factory\.hashtags/public.factory_hashtags/g; s/SET search_path.*//' > /tmp/fh.sql
scp ... /tmp/fh.sql root@NEW:/tmp/ && ssh ... 'docker cp /tmp/fh.sql contenthunter-postgres:/tmp/ && docker compose ... psql -U contenthunter -d contenthunter -f /tmp/fh.sql'
# device_state view (идемпотентный views.sql)
ssh ... 'docker exec -i contenthunter-postgres psql -U contenthunter -d contenthunter < /opt/contenthunter/_ops/db/views.sql'
```

- [ ] **Step 4: Миграции client + старт прод-процессов с TEST_MODE=1 (без публикации)**

```bash
ssh ... root@NEW '
  cd /opt/contenthunter/prod-client/backend && .venv/bin/alembic upgrade head
  cd /opt/contenthunter
  # временно прод-delivery с TEST_MODE=1 — поправить env на запуск или экспортнуть
  pm2 start ecosystem.prod.config.js
  pm2 save
  pm2 ls
'
```
(`prod-delivery` `.env` на этом шаге содержит `TEST_MODE=1` → публикация и фоновые джобы НЕ идут.)

- [ ] **Step 5: Сверка данных** — row counts ключевых таблиц `contenthunter` (prod) vs зафиксированные в Task 4 Step 3. Должны совпасть.

---

### Task 6: Caddy прод-домены + смоук прод (в окне)

- [ ] **Step 1: Caddy на NEW — прод-блоки**

Добавить в `/etc/caddy/Caddyfile` на NEW: `prod-delivery.contenthunter.ru → reverse_proxy localhost:3848`; `prod-client.contenthunter.ru` (handle /api/* → localhost:8000; статика из `/opt/contenthunter/prod-client/frontend/dist`). `caddy validate && systemctl reload caddy`. Дождаться TLS.

- [ ] **Step 2: Смоук прод (БЕЗ реальной публикации — TEST_MODE ещё включён)**

- Вход на `https://prod-delivery.contenthunter.ru` и `https://prod-client.contenthunter.ru` РЕАЛЬНЫМИ боевыми учётками (данные не обезличены).
- Дашборды, очереди, аналитика — рендерятся, данные на месте.
- Статус устройств (`/api/devices`) — заполняется (после старта collectDeviceMetrics; на TEST_MODE=1 джоб выключен → device_state пуст до включения; проверить после Task 7, либо разово дёрнуть `POST /api/sla/collect`).
- Доступ к S3/ADB-шлюзу/ffmpeg с NEW — подтвердить (хендшейк, не только TCP).

Expected: оба прод-интерфейса работают на реальных данных, публикация ещё не идёт.

---

### Task 7: Включение публикации + переключение доменов (в окне)

- [ ] **Step 1: Включить фоновые задания/публикацию на prod-delivery**

Убрать `TEST_MODE=1` из `/opt/contenthunter/prod-delivery/.env` (или выставить `0`), `pm2 restart prod-delivery prod-delivery-unic --update-env`. Теперь `collectDeviceMetrics`, `dispatchPublishQueue` и т.д. работают.

- [ ] **Step 2: Проверить, что публикация поднялась штатно**

`pm2 logs prod-delivery --lines 50` — диспетчер берёт задачи, collectDeviceMetrics опрашивает малинки (`autowarm_device_metrics` пишется, device_state наполняется). Убедиться, что нет шторма ошибок.

- [ ] **Step 3: 301-редирект старых доменов на новые (на OLD)**

Заменить в `/etc/caddy/Caddyfile` на OLD блоки `client`/`delivery` на редирект:
```caddy
client.contenthunter.ru {
    redir https://prod-client.contenthunter.ru{uri} permanent
}
delivery.contenthunter.ru {
    redir https://prod-delivery.contenthunter.ru{uri} permanent
}
```
`caddy validate && systemctl reload caddy`. Это снимает и плашку (старый домен теперь редиректит).

- [ ] **Step 4: Проверка редиректа**

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" https://client.contenthunter.ru/
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" https://delivery.contenthunter.ru/login
```
Expected: 301 → `https://prod-client/prod-delivery.contenthunter.ru/...`.

---

### Task 8: Завершение окна + наблюдение

- [ ] **Step 1: Открыть доступ** — сообщить команде, что переезд завершён, новые адреса = `prod-*`.
- [ ] **Step 2: Наблюдение сутки** — done-rate публикаций, статус устройств, ошибки в логах prod-delivery/prod-client, успешность авто-деплоя (push в develop→test, main→prod).
- [ ] **Step 3: Откат-план (на случай проблемы в окне):** снять редирект на OLD, вернуть блоки client/delivery на OLD localhost:8000/3848, разморозить писателей OLD (`pm2 start 35 36 ...`), вернуть cron. OLD-данные не тронуты → откат быстрый.

---

### Task 9: Пост-переезд (после стабилизации, вне окна)

- [ ] **Step 1: Остановить CH-сервисы на OLD насовсем** (id 35/36/33/26/28/29 + auth/producer если ещё живы) — **только CH**; другие продукты на OLD (systematika, hr, analytics, meeting-summaries и т.д.) ОСТАЮТСЯ работать.
- [ ] **Step 2: Удалить внешнюю factory-БД** `193.124.112.222` (старая платформа) — после подтверждения, что ничего на неё не завязано (Фаза 0: factory_sync отключён, device_state отвязан, FACTORY_DB вычищен).
- [ ] **Step 3: Очистить CH-чекауты/контейнер БД на OLD** (после N дней горячего бэкапа): остановить `openclaw-postgres`? — НЕТ, если другие продукты делят кластер; уточнить, кто ещё в БД `openclaw` (LiteLLM/systematika/CRM там же!) — **БД openclaw на OLD НЕ удалять, пока её используют другие продукты**. Удалить только CH-таблицы при необходимости (низкий приоритет).

---

## Self-Review

- **Покрытие:** промоушен кода (T1), прод-стенды (T2), плашка (T3), заморозка (T4), дамп+restore+views+старт (T5), caddy+смоук (T6), публикация+редирект (T7), завершение/откат (T8), пост-переезд (T9). Все пункты спека (раздел «Последовательность переезда» + «Обновление после разведки») покрыты.
- **Риски учтены:** контролируемый старт публикации (TEST_MODE), сверка row counts, откат-план, OLD-БД общая (не удалять), внешний factory отвязан.
- **Открытые параметры для исполнения:** IP Данила (плашка allowlist), точный `-T` дроп-лист (из Task 10 Фазы 0 — 75 таблиц), решение по `DAILY_REPORT` на время окна.
