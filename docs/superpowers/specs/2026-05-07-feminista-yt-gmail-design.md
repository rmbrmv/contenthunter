# Feminista YT-gmail — design

**Date:** 2026-05-07
**Sub-project of:** B (Feminista YT/IG/TT publish failures)
**Scope:** YT-gmail только (IG / TT отдельные sub-tasks)
**Repo:** `autowarm-testbench` (`GenGo2/delivery-contenthunter`, branch `testbench` → prod main)

## Контекст

Проект «Патчи для глаз Feminista» (validator_projects.id=100, api_name=Feminista) — новый, развёрнут в 3 паках (factory_pack_accounts.id=402/403/404) на устройствах #154/155/156 (raspberry #9). 9 публикационных задач (publish_tasks #3222–3247, 2026-05-07 ночью) упали:

- **YT (3247/3246/3243):** `yt_target_not_in_picker_after_scroll: target='feminista_*' gmail=None`. Все 3 YT-строки в `factory_inst_accounts` имеют `gmail=NULL` — switcher (`account_switcher.find_yt_row_by_gmail`) обязан матчить inactive-row через gmail (см. `project_yt_gmail_switcher.md`, миграция 2026-04-24).
- **IG (3229/3226/3222):** `ig_target_not_in_picker` / `watchdog_subprocess_hang` — out of scope.
- **TT (3239/3237/3233):** `tt_target_not_on_device` / `switch_failed_unspecified` — out of scope.

Текущая система не позволяет ввести gmail при создании/редактировании пака (форма имеет только `platform / username / user_id / active`), а `account_revision.py` обнаруживает gmail на устройстве, но обновляет только новых "discovered" аккаунтов; для уже зарегистрированных строк gmail остаётся `NULL` (см. `account_revision.py:548-568`).

## Цели

1. **Закрыть процесс-gap:** при создании YT-аккаунта gmail обязателен — невозможно сохранить YT-аккаунт в пак без gmail.
2. **Safety net:** Ревизия дозаполняет `gmail` для зарегистрированных YT-строк с `NULL`, читая YT picker устройства.
3. **Один источник истины** для парсинга YT picker — общий модуль, переиспользуемый между `account_revision.py` и `backfill_yt_gmails.py`.

## Не-цели

- Backfill 100+ существующих YT-строк с `NULL` gmail — будет выполнен инкрементально через Ревизию по мере её прогона на устройствах, либо разовый `backfill_yt_gmails.py --all` post-deploy.
- IG `ig_target_not_in_picker` failures (отдельный sub-task B-IG).
- TT `tt_target_not_on_device` failures (отдельный sub-task B-TT).
- Re-queue 9 failing Feminista publish_tasks (deploy-step после фикса).
- Изменения в `validator-contenthunter` (этот спек только на autowarm).

## Архитектура

4 точки изменений, все в `autowarm-testbench`:

### 1. Новый shared-модуль `yt_gmail_probe.py`

Создать на root репы (рядом с `account_switcher.py`, `account_revision.py`, `backfill_yt_gmails.py`).

**Публичные функции (чистые, без DB):**

```python
def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    """Парсит UI dump YT picker'а в пары (display_name, gmail).

    Дано: XML hierarchy dump с raw-text элементами вида
    'Makiavelli Inakent (makiavelli485@gmail.com)' или structured
    'display=Makiavelli, desc=makiavelli485@gmail.com\n5K subscribers'.

    Возвращает: список пар, или [] если picker пустой / не загружен.
    """

def match_gmail_to_handle(
    handle: str,
    pairs: list[tuple[str, str]],
) -> Optional[str]:
    """Найти gmail для @handle в списке пар (display_name, gmail).

    Логика matching (заимствуется из backfill_yt_gmails.py):
      1. exact-match: handle.lower() == display_name.lower().replace(' ', '')
      2. prefix-match: gmail.split('@')[0].lower() == handle.lower()
      3. handle-prefix vs display-name suffix: feminista_patches → 'Feminista patches'

    Если найдено 0 → None. Если ровно 1 → gmail. Если >1 → None
    (caller логирует ambiguous).
    """

def probe_yt_gmails_live(
    adb_host: str,
    adb_port: int,
    serial: str,
) -> list[tuple[str, str]]:
    """Открывает YT → profile tab → picker, дампит UI, возвращает пары.

    Side effects: am force-stop com.google.android.youtube → launch →
    tap profile-tab (972, 2320) → tap account-switch row → uiautomator dump →
    pull XML → extract_yt_picker_pairs.

    Не закрывает YT после probe (caller решает).
    """
```

**Тестируемость:** `extract_yt_picker_pairs` и `match_gmail_to_handle` — pure functions, тестируются на XML-фикстурах. `probe_yt_gmails_live` — тонкая обёртка над ADB + extract.

### 2. Рефакторинг `backfill_yt_gmails.py`

Текущая логика (regex `GMAIL_RE`, `HANDLE_RE`, `DELETED_LABEL_RE`, парсинг picker'а в `process_device`) — перенести в `yt_gmail_probe.py` где переиспользуется. CLI поведение не меняется. Существующие тесты остаются зелёными.

### 3. `account_revision.py`

**`discover_gmails`** (текущая строка 280) — переписать поверх `yt_gmail_probe.probe_yt_gmails_live`. Сигнатура меняется: `-> list[tuple[str, str]]` (пары `(display_name, gmail)` вместо `list[str]`).

**Backward compat для frontend:** `result['gmails']` сейчас рендерится как chip-список в `public/index.html:6354`. Чтобы не ломать рендер, `run()` сохраняет:

```python
pairs = self.discover_gmails()
result['gmails_pairs'] = [{'display_name': d, 'gmail': g} for d, g in pairs]
result['gmails'] = [g for _, g in pairs]  # backward-compat: list[str] для chip-рендера
```

Места в `account_revision.py`, читающие `result['gmails']` как строки (строка 550 — выбор `gmail = result['gmails'][0] if len == 1 else None` для discovered new accounts; строка 585 — итерация для информационного логирования; строка 599 — `len(result['gmails']) > 0`), продолжают работать без изменений.

**Новый шаг в `run()`** между `per_platform_status` циклом и финальным `result['errors']`:

```python
# Backfill NULL gmails для зарегистрированных YT-строк device'а.
self._progress('gmails_backfill', 'Дозаполнение gmail для YouTube...', 80)
backfilled = []
yt_pairs = pairs  # из discover_gmails() выше
if yt_pairs:
    with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT fia.id, fia.username
              FROM factory_inst_accounts fia
              JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
             WHERE fpa.device_num_id = %s
               AND fia.platform = 'youtube'
               AND fia.active = TRUE
               AND fia.gmail IS NULL
            """,
            (self.device_num_id,),
        )
        rows = cur.fetchall()
    for acc_id, username in rows:
        gmail = match_gmail_to_handle(username, yt_pairs)
        if not gmail:
            logger.info('[revision] gmail_no_match handle=%s', username)
            continue
        try:
            with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
                cur.execute(
                    'UPDATE factory_inst_accounts SET gmail=%s WHERE id=%s AND gmail IS NULL',
                    (gmail.lower(), acc_id),
                )
                conn.commit()
                if cur.rowcount == 1:
                    backfilled.append({'account_id': acc_id, 'username': username, 'gmail': gmail.lower()})
                    logger.info('[revision] gmail_backfilled handle=%s gmail=%s', username, gmail)
        except Exception as e:
            logger.warning('[revision] gmail_backfill_failed handle=%s err=%s', username, e)
            continue
result['gmails_backfilled'] = backfilled
```

UPDATE-per-row, не batched — partial progress лучше чем zero.

### 4. UI и backend

#### Frontend (`public/index.html`)

- **`pkgShowAddAccountRow`** (≈8941): после input username добавить ячейку с input `id="new-acc-gmail"` и hint `gmail (для YT)`. Изначально hidden (`style.display='none'`); JS-handler на `#new-acc-platform.change`: показать когда `value==='youtube'`, спрятать иначе.
- **`pkgSaveNewAccount`** (≈8988): прочитать gmail из `#new-acc-gmail`. Если `platform==='youtube'`:
  - если `!gmail.trim()` → `toast('Для YouTube gmail обязателен', 'error'); return;`
  - если `!gmail.includes('@')` → `toast('gmail должен содержать @', 'error'); return;`
- **Account row rendering** в `pkgLoadAccounts` (≈8822): для YT-строки рядом с username показать `<span class="text-xs text-gray-500">${gmail || '—'}</span>`; в edit-режиме — input `.acc-gmail-input` (только для YT, иначе hidden).
- **`pkgSaveAccount`** (edit, ≈8893): шлёт gmail в payload; если platform=youtube и пользователь очистил gmail (был и стал пустым) — `toast('Нельзя очистить gmail', 'error'); return;`.
- **`savePackage`** + GET `/api/packages` рендеринг: gmail-колонка в outer pack-list уже не нужна (per-account, не per-pack); accounts-таблица внутри пак-модала — туда добавить.

#### Backend (`server.js`)

- **POST `/api/packages/:id/accounts`** (3802):
  ```js
  const { platform, username, user_id, active, gmail } = req.body;
  // ...existing username/dup checks...
  let gmailNorm = null;
  if (platform === 'youtube') {
    if (!gmail || !gmail.trim()) {
      return res.status(400).json({ error: 'gmail обязателен для YouTube' });
    }
    gmailNorm = gmail.trim().toLowerCase();
    if (!gmailNorm.includes('@')) {
      return res.status(400).json({ error: 'gmail должен содержать @' });
    }
  }
  // INSERT расширяется на gmail колонку
  `INSERT INTO factory_inst_accounts (pack_id, platform, username, instagram_id, active, gmail, synced_at)
   VALUES ($1,$2,$3,$4,$5,$6,NOW()) RETURNING id, username, instagram_id AS user_id, platform, active, gmail, date_last_parsing`
  ```
- **PUT `/api/packages/accounts/:accountId`** (3841):
  ```js
  const { username, active, gmail } = req.body;
  // Прочитать current gmail для проверки clear-to-NULL
  const { rows: [cur] } = await pool.query(
    'SELECT platform, gmail FROM factory_inst_accounts WHERE id=$1', [accountId]
  );
  if (!cur) return res.status(404).json({ error: 'Аккаунт не найден' });
  let gmailUpdate = cur.gmail;  // default: оставить как есть
  if (gmail !== undefined) {
    if (cur.platform === 'youtube' && cur.gmail && (!gmail || !gmail.trim())) {
      return res.status(400).json({ error: 'нельзя очистить gmail у существующего аккаунта' });
    }
    if (gmail && gmail.trim()) {
      const g = gmail.trim().toLowerCase();
      if (!g.includes('@')) return res.status(400).json({ error: 'gmail должен содержать @' });
      gmailUpdate = g;
    }
  }
  `UPDATE factory_inst_accounts SET username=$1, active=$2, gmail=$3 WHERE id=$4 RETURNING ...`
  ```
- **GET `/api/packages/:id/accounts`** (3793): SELECT расширяется на `gmail`.
- **GET `/api/packages`** (3316): `JSON_BUILD_OBJECT` расширяется на `'gmail', fia.gmail`.

## Data flow

### A. Создание нового пака с YT-аккаунтом (Feminista)

1. Оператор → «Паки» → «+ Новый пак» → project=Feminista, device=#154 → POST `/api/packages` (создаётся пустой пак).
2. «Добавить аккаунт» → `pkgShowAddAccountRow` рендерит форму с скрытым gmail-полем.
3. Selector platform → `youtube` → JS unhide gmail-input.
4. Username `feminista_patches` + gmail `feminista155@gmail.com` → Сохранить.
5. POST `/api/packages/:id/accounts` `{platform:'youtube', username:'feminista_patches', gmail:'feminista155@gmail.com', active:true}`.
6. Backend: validate → normalize → INSERT.
7. Frontend перерисовывает таблицу пака.

### B. Ревизия (safety net)

1. Оператор → «Устройства» → клик на serial → «Ревизия».
2. SSE `/api/devices/:serial/revision` → server запускает `account_revision.py`.
3. Скрипт:
   - IG/TT/YT discovery как сейчас.
   - **Новое:** `yt_pairs = probe_yt_gmails_live(host, port, serial)` → `[('Makiavelli', 'makiavelli485@gmail.com'), ('Feminista patches', 'feminista155@gmail.com')]`.
   - SELECT YT-строк device_num_id с `gmail IS NULL` и `active=true`.
   - Для каждой: `match_gmail_to_handle(handle, pairs)` → если match → UPDATE.
4. Result JSON: `gmails_backfilled: [{account_id, username, gmail}]`.
5. Frontend: «✅ Дозаполнен gmail: feminista_patches → feminista155@gmail.com (1 шт)».

### C. Edit аккаунта (manual fix)

1. Клик «✏️» на YT-row.
2. Inline-редактор показывает username + gmail.
3. PUT `/api/packages/accounts/:accountId` `{username, gmail, active}` → UPDATE.

## Edge cases / error handling

| Сценарий | Поведение |
|---|---|
| ADB падает в `probe_yt_gmails_live` | log warning `yt_gmail_probe_failed`, `pairs=[]`, backfill no-op, основной revision flow продолжается |
| YT picker пуст / не открылся | `pairs=[]`, no-op (телефон не залогинен в YT — нормальный кейс) |
| `match_gmail_to_handle` нашёл >1 кандидата | skip, log `gmail_match_ambiguous handle=X candidates=[...]` |
| Match только prefix, не exact | apply (основной кейс — `feminista_patches` ↔ `Feminista patches`); логировать match-mode |
| Match не найден | skip, log `gmail_no_match`. Оператор позже вводит руками. |
| POST YT без gmail | 400 (frontend ловит раньше; backend — defence-in-depth) |
| POST gmail без `@` | 400 |
| PUT попытка очистить непустой gmail | 400 `'нельзя очистить gmail'` |
| Backfill UPDATE падает (DB error) | rollback per-row, log warning, продолжаем остальные |
| Race: между SELECT и UPDATE другой процесс заполнил gmail | UPDATE WHERE `gmail IS NULL` — `rowcount=0`, log info, не считаем backfilled |

## Тесты

- **`tests/test_yt_gmail_probe.py`** (новый):
  - `extract_yt_picker_pairs`: фикстуры XML с 0 / 1 / 2+ парами; mixed gmail/non-gmail домены; "Канал удалён" rows.
  - `match_gmail_to_handle`: exact, prefix, ambiguous, no-match.
- **`tests/test_backfill_yt_gmails.py`** (если уже есть — должен остаться зелёным после рефакторинга; если нет — добавить smoke против существующего фикстура `--dump`).
- **`tests/test_revision_real_adb.py`** (расширить): после revision на phone #19 проверить, что предварительно обнулённая `gmail` для зарегистрированного YT восстановилась.
- **Backend smoke** (встроить в существующий test-suite или новый `tests/integration/packages_gmail.test.js`): POST YT без gmail → 400; POST YT с gmail → row.gmail=lowercase; PUT clear non-null gmail → 400.
- **Frontend manual smoke** (записать в evidence post-deploy): добавить YT через UI → verify в DB; reload → gmail показан; edit → success.

## Deploy plan

1. Merge → prod main → auto-push hook → PM2 reload (`pm2 reload autowarm` для server.js + nginx serve обновлённый `public/index.html`).
2. Post-deploy: восстановить gmail для Feminista либо:
   - Manual: оператор открывает каждый из 3 паков (402/403/404) → edit YT-row → ввести gmail → save.
   - Автомат: после ручного логина YT-аккаунтов на phones #154/155/156, прогнать `python3 backfill_yt_gmails.py --device-number 154 --device-number 155 --device-number 156`.
3. Re-queue 9 failing Feminista publish_tasks через `publish_queue` (см. `reference_publish_requeue_path.md`): `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE publish_task_id IN (3222, 3226, 3229, 3233, 3237, 3239, 3243, 3246, 3247);` — dispatchPublishQueue (5min) создаст новые `publish_tasks`.
4. Smoke validate: следующий cycle Feminista YT не должен возвращать `yt_target_not_in_picker_after_scroll: gmail=None`.

## Out of scope (backlog)

- One-off backfill 100+ существующих YT с `gmail=NULL` через `backfill_yt_gmails.py --all` (после деплоя как ops-task).
- IG `ig_target_not_in_picker` для feminista_glow / feminista_patches (sub-task B-IG).
- TT `tt_target_not_on_device` (sub-task B-TT).
- Re-queue Feminista publish_tasks (deploy-step выше).
- Аудит остальных проектов на gmail-NULL — отдельный SQL report.
