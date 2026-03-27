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
| autowarm | workspace-genri/autowarm, port 3849 | Publisher + Warmer, PM2 |

---

## Lessons Learned
*Distilled from anti-patterns. Things to always remember.*

## 2026-03-25 — publisher.py: Instagram/YouTube описание не вводилось

### Instagram — диалог «Название аудиодорожки» (коммит `3c0a09a`)
**Контекст:** после нажатия «Поделиться» Instagram показывает ModalActivity с запросом имени звука.
**Ошибка:** `KEYCODE_BACK` на этом диалоге **отменяет** публикацию, возвращает на caption screen, поле пустое.
**Правило:** использовать только `Пропустить`/`Skip`/`Не сейчас`. Никогда — Back/Cancel/KEYCODE_BACK в аудио-диалоге.
**Страховка:** при возврате на caption screen — автоматически перевводим caption.

### YouTube — заголовок до кнопки Upload (коммит `053e904`)
**Контекст:** в цикле редактора YouTube экран «Название» и кнопка «Загрузить» видны одновременно.
**Ошибка:** если `Загрузить` проверяется раньше `Название/Title` → публикуется без заголовка и описания.
**Правило:** блок `Title/Название` всегда должен быть **первым** в цикле редактора, до `Upload/Загрузить`.

- Файл: `workspace-genri/autowarm/publisher.py`

---

## Rules Discovered
*Patterns learned from experience that aren't in SOUL.md yet*

- {rule 1}
- {rule 2}

---

## TODO
- [ ] {task}

## autowarm — фикс publish_tasks: отсутствующие колонки (2026-03-23)

**Проблема:** все задачи публикации падали: `column pt.pre_warm_protocol_id does not exist`.

**Фикс:**
```sql
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS pre_warm_protocol_id INTEGER,
  ADD COLUMN IF NOT EXISTS post_warm_protocol_id INTEGER;
```

**Правило:** при разворачивании autowarm на новом сервере — проверить наличие этих колонок в `publish_tasks`.
**Сброс задачи из failed → pending:** `UPDATE publish_tasks SET status='pending', log='', started_at=NULL WHERE id=<id>;`
