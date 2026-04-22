# Evidence — refactor-revision-use-switcher-engine-20260422

**Дата:** 2026-04-22 UTC
**План:** [`refactor-revision-use-switcher-engine-20260422.md`](../plans/refactor-revision-use-switcher-engine-20260422.md)
**Репозитории:** `autowarm-testbench@testbench`, `contenthunter@main`

## Проблема

На phone #171 (`RF8Y90GCWWL`, `factory_device_numbers.id=268`) модалка `Ревизия аккаунтов` не находила реально залогиненные `born.trip90` / `ivana.world.class` в IG/TT/YT. Скрапер `account_revision.py`:
- IG: фолз на sanity-check'е (3KB пустой dump)
- TT: «wrong_foreground=instagram» — IG липнет после force_stop
- YT: fallback regex `_extract_username_from_ui` ловил мусор из меню (`ibydiva`, `@cxpnax`, `@russan`)
- В БД попали фейковые YT-записи (`factory_inst_accounts.id=1630/1631`) от прошлого мусорного прогона

## Решение

Вариант B2.5 — добавить read-only микро-API в `AccountSwitcher`, перевести `account_revision.py` на этот API, убрать дубликаты UI-логики. `ensure_account()` и `publisher.py` не трогаем (нулевой риск для phone #19).

---

## Шаг T1 — Чистка БД на #171 (выполнено 2026-04-22 UTC)

### BEFORE

```
factory_inst_accounts на phone #171 (device_number=171):
  id   | pack_id | pack_name             | platform | username | synced_at
  1630 | 308     | Тестовый проект_171a  | youtube  | ivana    | 2026-04-22 13:49:00
  1631 | 309     | Тестовый проект_171b  | youtube  | google   | 2026-04-22 13:51:22

Pack counts:
  pack 308 (171a) → 1 account (фейковый)
  pack 309 (171b) → 1 account (фейковый)
```

### Действие

```sql
BEGIN;
DELETE FROM factory_inst_accounts WHERE id IN (1630, 1631);
COMMIT;
-- DELETE 2
```

### AFTER

```
factory_inst_accounts на phone #171: (0 rows)

Pack counts:
  pack 308 (171a) → 0 accounts (готов принять live-прогон)
  pack 309 (171b) → 0 accounts (готов принять live-прогон)
```

### Rollback (если потребуется)

```sql
INSERT INTO factory_inst_accounts (id, pack_id, platform, username, active, synced_at) VALUES
  (1630, 308, 'youtube', 'ivana',  true, '2026-04-22 13:49:00.753883'),
  (1631, 309, 'youtube', 'google', true, '2026-04-22 13:51:22.154577');
```

---

## Шаги T2-T12 — будут заполняться по мере выполнения
