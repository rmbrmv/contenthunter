# HEARTBEAT.md

## Проверка новых pairing запросов
1. Прочитай `/root/.openclaw/credentials/telegram-pairing.json`
2. Прочитай `/root/.openclaw/workspace/memory/pairing-notified.json` (уже уведомлённые)
3. Если есть новые запросы (userId которых нет в notified) — отправь Роману сообщение:
   "🔔 Новый запрос на доступ: [Имя] (@username) → [название бота]. Одобрить: https://dashboard.contenthunter.ru"
4. Сохрани userId в pairing-notified.json чтобы не дублировать

## Мониторинг Telegram канала
1. Выполни `openclaw gateway status 2>&1` и проверь что Runtime: running
2. Выполни `openclaw status --deep 2>&1` и проверь что Telegram → OK
3. Если канал не OK или gateway не running:
   - Выполни `openclaw gateway restart`
   - Отправь Роману: "⚠️ Telegram канал отвалился, перезапустила gateway"
4. Если всё OK — ничего не делай

## Проверка размеров memory у агентов
1. Для каждого workspace-* проверь размер файлов в `memory/` и `learning/`
2. Если любой файл > 50KB — сожми: оставь последние 20 записей, остальное в архив `memory/archive/`
3. Если SOUL.md > 15KB — предупреди Романа: «SOUL.md у [агент] раздулся, нужна чистка»
4. Проверяй раз в 2-3 дня, не каждый heartbeat

## TODO
- ~~Вова-сисадмин SOUL.md~~ ✅ сделано 26.02

## Проверка новых агентов без SOUL.md
1. Прочитай `agents.list` из `~/.openclaw/openclaw.json`
2. Прочитай `/root/.openclaw/workspace/memory/agents-known.json` (уже известные agentId)
3. Для каждого нового agentId (которого нет в known):
   - Проверь существует ли `/root/.openclaw/workspace-{agentId}/SOUL.md` и больше ли 200 байт
   - Если SOUL.md нет или он пустой — спроси Романа:
     "🤖 Новый агент: [Имя]. Расскажи кто он — я напишу ему SOUL.md!"
4. Сохрани agentId в agents-known.json
