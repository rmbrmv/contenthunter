# MEMORY.md — Long-term Memory

*This is distilled memory. Raw logs live in `memory/YYYY-MM-DD.md`. Update this weekly.*

---

## User
- Роман (@rmbrmv, 295230564) — owner
- 

---

## Key Decisions
*Important decisions made, why, and what we chose*

<!-- Format:
## YYYY-MM-DD — {decision title}
Chose: {option}
Why: {reason}
-->

---

## Infrastructure
*Services, paths, ports relevant to this agent*

| What | Where | Notes |
|------|-------|-------|
| {service} | {path/url} | {notes} |

---

## Lessons Learned
*Distilled from anti-patterns. Things to always remember.*

- {lesson 1}
- {lesson 2}

---

## Rules Discovered
*Patterns learned from experience that aren't in SOUL.md yet*

- {rule 1}
- {rule 2}

---

## TODO
- [ ] {task}

## validator — UsersManagement обновление (2026-03-23)

- `/admin/users`: sticky header, сортировка по столбцам, строка фильтров (пользователь/роль/проект/статус)
- Создано 38 client-пользователей для всех активных проектов
  - Логин = api_name проекта (напр. `booster_cap`, `relisme`)
  - Временный пароль: `123456789` (нужна смена при передаче клиентам)
  - role=client, project_id привязан
- Коммиты: `defb4f3`, `f7ce54a` → GenGo2/validator-contenthunter

## validator — аккаунты тестового проекта (2026-03-23)

Тестовый проект (project_id=10) получил привязанные аккаунты на `/accounts`:
- YouTube: `Инакент-т2щ` | Instagram: `inakent06` | TikTok: `user70415121188138`
- Пак: id=249, `Тестовый проект_19`, устройство #19 (serial RF8YA0W57EP)

Синхронизация с удалённой factory БД отключена — все данные теперь в локальной public-схеме.


## validator — async upload validation (2026-03-23, Генри)

POST /api/upload/file теперь возвращает ответ сразу (status=validating), без ожидания транскрипции/OCR.
Валидация бежит в фоне через asyncio.create_task.
Новый endpoint: GET /api/upload/status/{content_id} — для опроса готовности.
Фронт сам делает polling каждые 3 сек и показывает стадии.
Это фикс 502 при загрузке видео через планировщик.
Коммит: 8095ec8 в GenGo2/validator-contenthunter

