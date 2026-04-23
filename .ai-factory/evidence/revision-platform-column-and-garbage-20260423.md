# Revision: PLATFORM_TO_COLUMN + мусор в модалке — постмортем и фикс

**Дата:** 2026-04-23
**Plan:** `.ai-factory/PLAN.md` (fast mode)
**Репо:**
- autowarm-testbench: `testbench` ветка, commit `025ae18`
- prod `/root/.openclaw/workspace-genri/autowarm/`: переключён с orphan `feature/testbench-iter-4-publish-polish` на `testbench` @ `025ae18`
- contenthunter: `main`

## Наблюдения пользователя

1. Скрин Yandex Disk `78Jb_momm3hofQ`: модалка «Ревизия аккаунтов» → в таблице «Новые аккаунты» строки с фоновым текстом экрана (не username'ы) — «публикации», «подписчики», «введите», «транслировать», русские и казахские label'ы.
2. Скрин `xHpRbKPmR82Hig`: при «Применить» по корректным строкам — `Ошибка: PLATFORM_TO_COLUMN is not defined`.

## Корневые причины

### RC-A: `PLATFORM_TO_COLUMN is not defined` (server.js:3271)

Legacy-обращение к удалённому маппингу.

До `DROP TABLE account_packages` (2026-04-22, evidence: `deprecate-account-packages-20260422.md`) в server.js существовал `PLATFORM_TO_COLUMN = {instagram: 'ig_account', tiktok: 'tt_account', youtube: 'yt_account'}` — использовался для маршрутизации вставки в колонки `account_packages`. После drop'а и миграции вставки на `factory_inst_accounts.platform` (строковое поле, не колонка per-platform), map стал не нужен — но строка `const column = PLATFORM_TO_COLUMN[platformLc]` на 3271 осталась.

Единственное использование `column` — `if (!column) continue;` (whitelist-проверка out-of-scope платформ). Правильный фикс — явный whitelist, без мёртвого lookup'а.

### RC-B: Мусорные «аккаунты» в модалке

**Главная причина:** prod `/root/.openclaw/workspace-genri/autowarm/` отставал от `testbench` ветки на 9 коммитов. Prod работал со СТАРЫМ `account_revision.py` (1052 строки), в котором `discover_platform_accounts` → `_read_accounts_list` → `_extract_username_from_ui` (regex fallback, возвращал первый non-trivial текст с экрана как username). Отсюда мусор вроде «публикации», «подписчики».

Свежий testbench уже имел:
- `refactor(revision): use switcher.read_accounts_list as UI engine` (114486c) — убирает regex-fallback, делает revision тонким CLI-обёрткой.
- `fix(switcher-ro): require dropdown anchor + revision dump-dir override` (99220ce) — при отсутствии якоря «Добавить аккаунт» возвращает current-only, не парсит весь экран.
- `fix(switcher-ro): IG Meta-Center anchors + TT own-profile guard` (f0f109f).
- `fix(switcher-ro): TT cold-restart, YT non-usable retry, IG noise filter` (cfa50af).

Но ничего из этого не доехало до prod'а. Deploy hook автопушит commit'ы из prod → remote, но НЕ затягивает remote → prod. Pull/checkout на prod делается вручную (мы не делали с 22 апреля).

**Дополнительный hardening** для защиты от будущих регрессий:
- `container_y_range` у `parse_account_list` был шириной 1500 px от якоря — на 1080×2400 экранах это почти весь экран. Достаточно было якорю «найтись» не в dropdown'е, и parser тащил фон как accounts.
- `_USERNAME_RE = r'^@?[\w.\-]{2,40}$'` с Unicode-флагом + правилом `has_digit_or_sep OR len>=5` пропускал чисто-кириллические label'ы ≥5 символов (русский/казахский/арабский).
- `_USERNAME_STOPWORDS` — ~60 слов, недостаточно для наблюдаемого мусора.

## T1: Investigation (факты из дампов)

`/tmp/autowarm_revision_dumps/` — 205 XML после refactor деплоя на testbench. Прогнал `parse_account_list(elements, None)` (без container range, т.е. режим прод'а со старым кодом):

IG profile (phone #171): мусорные токены, которые старый код мог выдать как accounts:
```
публикации, 0подписчики, подписчики, биографию, баннеры, редактировать,
профилем, интересные, начала, подпишитесь, использовать, чтобы,
человек, продолжить
```

TT profile: `профиля, историю, born7499, подписчиков, лайки, описание, публикации, приватные, заблокировать, избранное, понравившиеся, фотографии, камера`.

YT profile (KZ-локаль): `транслировать, введите, запрос, канал, плейлисты, новый, плейлист, действий, создание, фильмы, попробуйте, premium, ограничения., воспроизвести, короткое, минуты, секунд, канале, выгнали, унижение, сюжетный, парень, сразил, аллаhа, история`.

Все они использовали эвристику `len>=5` для прохождения username-фильтра.

## T2-T5: Фиксы

### T2 — `PLATFORM_TO_COLUMN` → `ALLOWED_PLATFORMS`

`server.js`:
```javascript
const ALLOWED_PLATFORMS = new Set(['instagram', 'tiktok', 'youtube']);
...
if (!ALLOWED_PLATFORMS.has(platformLc)) {
  console.warn(`[revision/apply] skip out-of-scope platform=${acc.platform} acc=${acc.username}`);
  continue;
}
```

### T3 — сузить dropdown container + sanity на позицию якоря

`account_switcher.py:read_accounts_list`:
```python
# Sanity: якорь в header'е → suspicious position → current-only
header_y_max = cfg['profile_title_header_y_range'][1]
if anchor_bounds[1] < header_y_max + 200:
    return {'platform': plat_norm, 'status': 'error',
            'current': current, 'accounts': [current] if current else [],
            'reason': 'anchor_in_suspicious_position', ...}

DROPDOWN_MAX_HEIGHT_PX = 1200
y_top = max(0, anchor_bounds[1] - DROPDOWN_MAX_HEIGHT_PX)
y_bot = anchor_bounds[3] + 50
container_y_range = (y_top, y_bot)
```

### T4 — ужесточить `_looks_like_username` + stopwords

```python
def _looks_like_username(s: str) -> bool:
    ...
    has_digit = any(c.isdigit() for c in s)
    has_sep = any(c in '._-' for c in s)
    has_latin = any('a' <= c <= 'z' for c in s)
    if has_digit or has_sep: return True
    # Без цифр/разделителей — требуем латинскую букву + len>=4.
    # Чистая кириллица — UI label.
    return has_latin and len(s) >= 4
```

`_USERNAME_STOPWORDS` расширен на 40+ токенов из T1.

### T5 — server-side USERNAME_RE

```javascript
const USERNAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{1,39}$/;
const unClean = (acc.username || '').trim().replace(/^@/, '');
if (!USERNAME_RE.test(unClean)) {
  skipped_invalid.push({ platform, username, reason: 'invalid_format' });
  continue;
}
acc.username = unClean;
```

Ответ `/revision/apply`: добавлен `skipped_invalid[]`.

UI: после success показывается `«Добавлено X (пропущено невалидных: Y)»`.

## Tests

```
pytest tests/test_switcher_read_only.py tests/test_account_switcher.py tests/test_switcher_youtube.py tests/test_overlay_dismiss.py
68 passed in 62.04s
```

Добавлено 3 новых:
- `test_looks_like_username_accepts_real_handles`
- `test_looks_like_username_rejects_cyrillic_ui_labels`
- `test_read_accounts_list_rejects_anchor_in_header_area`

## T7 — Deploy в prod

Prod был на orphan ветке `feature/testbench-iter-4-publish-polish` (HEAD=616421a). Переключён:
```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git checkout -b testbench --track origin/testbench   # → 025ae18
sudo pm2 restart autowarm                             # status=online, clean logs
```

Проверка:
- `server.js`: есть `ALLOWED_PLATFORMS`, `USERNAME_RE`; нет `PLATFORM_TO_COLUMN`.
- `account_switcher.py`: есть `DROPDOWN_MAX_HEIGHT_PX=1200`, `anchor_in_suspicious_position`, `read_accounts_list`.
- `account_revision.py`: 615 строк (новый thin-wrapper через switcher shim).
- pm2 logs — только обычные orchestrator/publisher записи, никаких ReferenceError.

## T6 — Live smoke

**Phone #171** (`RF8Y90GCWWL`, device_num_id=268, rig `82.115.54.26:15088`):

```
[revision] → discover_platform_accounts platform=instagram
[switcher-via-shim] switcher_read: success platform=Instagram count=2 current='ivana.world.class' accounts=['ivana.world.class', 'born.trip90']
[revision] ← instagram: status=found accounts=2

[revision] → discover_platform_accounts platform=tiktok
[switcher-via-shim] switcher_read: success platform=TikTok count=1 current='born' accounts=['born']
[revision] ← tiktok: status=found accounts=1

YouTube: timeout at 240s (не related to RC)
```

**Ключевое:** никаких `публикации`, `подписчики`, `транслировать` в accounts. Smoke подтверждает: (1) IG возвращает точный список без мусора, (2) TT возвращает валидный handle без мусора, (3) при проблемах запуска app'а → `status=error accounts=[]`, а не мусорный fallback.

**Phone #282** (`RF8Y91F8T6J`) — apps вообще не стартовали (`launch_failed_after_aggressive_reset`), revision вернул `accounts=[]`. Правильная деградация, не мусор.

## Коммиты

| Commit | Репо | SHA |
|---|---|---|
| fix(revision): strict username filter + drop PLATFORM_TO_COLUMN regression | autowarm-testbench/testbench + prod/testbench | `025ae18` |
| docs(plans+evidence): revision platform-column + garbage fix | contenthunter/main | (next) |

## Risks & fallback

- `DROPDOWN_MAX_HEIGHT_PX=1200` не покроет экстремальные экраны (tablets 2560 px) — подтягивается per-platform при необходимости.
- Ужесточённый `_looks_like_username` может отсечь редкий чисто-кириллический handle. Митиг: server-side `USERNAME_RE` — ASCII-only, поймает такие как `invalid_format` и вернёт их пользователю в `skipped_invalid[]` для ручной проверки. Всегда есть обратная связь.
- Rollback: `git reset --hard origin/testbench~1` в prod + `pm2 restart autowarm` вернёт состояние до 025ae18 (но регрессия `PLATFORM_TO_COLUMN` вернётся).

## Memory update

Обновлено:
- `feedback_plan_full_mode_branch.md` (уже user-added) — `/aif-plan` теперь всегда в режиме full+branch, чтобы PLAN.md не перетирали соседние сессии.
- `project_revision_phone171_backlog.md` уже содержит статус IG ✅ (теперь подтверждён и в проде).
