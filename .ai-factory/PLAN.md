# PLAN — Revision UI: мусорные «аккаунты» в модалке + `PLATFORM_TO_COLUMN is not defined`

**Тип:** fix (UI-скрейпинг hardening + server.js regression)
**Создан:** 2026-04-23
**Режим:** Fast — overwrite предыдущего PLAN.md (предыдущий testbench-start-stop уже отгружен, evidence в `.ai-factory/evidence/testbench-start-stop-button-20260423.md`).

**Репо:**
- Код: `/home/claude-user/autowarm-testbench/` (ветка `testbench`) — свои фиксы коммитим туда.
- Prod deploy: `/root/.openclaw/workspace-genri/autowarm/` — отдельный git repo с post-commit hook'ом → `GenGo2/delivery-contenthunter`. Ручной commit + `pm2 restart autowarm` в самом конце.
- Контекст плана/evidence: `/home/claude-user/contenthunter/` (main).

## Settings

- **Testing:** yes — unit-тесты для нового strict-container и расширенного stopwords; интеграционный smoke на живом устройстве (phone #171 или любом доступном).
- **Logging:** verbose — `[switcher-ro] dropdown_container y=(...) parsed=N filtered=M rejected=[...]`; `[revision/apply] skip out-of-scope platform=...`. Логируем отклонённые токены для быстрой итерации stopwords.
- **Docs:** warn-only — evidence обязателен, отдельного docs-коммита не требую (memory update — только если найдём новые правила).
- **Roadmap linkage:** none (`paths.roadmap` не настроен).

## Контекст — что наблюдается

Скрины пользователя (Yandex Disk):
1. `78Jb_momm3hofQ` — модалка «Ревизия аккаунтов»: в таблице «Новые аккаунты» отображаются произвольные строки с экрана (не валидные usernames) наряду с реальными.
2. `xHpRbKPmR82Hig` — при «Применить» по выбранным корректным строкам приходит `Ошибка: PLATFORM_TO_COLUMN is not defined`.

Evidence на диске: `/tmp/autowarm_revision_dumps/` — 205 XML-дампов последних прогонов (по device_serial), первичный материал для реконструкции, какой именно UI-шаг породил мусор.

## Корневые причины

### RC-A: `PLATFORM_TO_COLUMN is not defined` (server.js:3271)

Legacy-артефакт deprecated `account_packages`-таблицы. Раньше код писал в `ig_account/tt_account/yt_account` колонки и `PLATFORM_TO_COLUMN = {instagram: 'ig_account', ...}` использовался для маршрутизации. После `DROP TABLE account_packages` (2026-04-22, memory `project_account_packages_deprecation.md`) вставка перешла на `factory_inst_accounts.platform` (строковое поле), но строка `const column = PLATFORM_TO_COLUMN[platformLc]` осталась. Сама переменная `column` дальше **нигде не используется** (только в `if (!column) continue;` как whitelist-check out-of-scope платформ). `grep -n` в файле подтверждает: одно-единственное обращение.

Фикс: заменить на явный whitelist, убрать мёртвый lookup.

### RC-B: Мусорные «аккаунты» в модалке

`account_switcher.read_accounts_list()` имеет 2 протечки в парсинге dropdown'а:

**B1 — слишком широкий `container_y_range`.** Строки 724-725:
```python
container_y_range = (max(0, anchor_bounds[1] - 1500), anchor_bounds[3] + 50)
```
Если якорь «Добавить аккаунт»/«Switch account» нашёлся не в dropdown'е (IG/TT tap на header открыл не список, а другой экран со ссылкой «Добавить аккаунт» в подвале), окно в 1500 px вверх от anchor'а покрывает практически весь экран (телефоны phone #171 — 1080×2400). `parse_account_list` ловит random label'ы как usernames.

**B2 — либеральный `_looks_like_username`.** `_USERNAME_RE = r'^@?[\w.\-]{2,40}$'` с Unicode-флагом матчит любые кириллические/казахские/арабские слова длиной ≥5 (правило: `has_digit_or_sep OR len>=5`). `_USERNAME_STOPWORDS` содержит около 60 русских/английских системных слов, но в проде видно, что многие пропускаются (KZ локаль YT — `Есептік жазбалар`, TT — `Ұсыныстар`, арабские токены; RU — `загрузки`, `рекомендации`, `подписки`, `активность` и т.п.).

Дополнительно `parse_account_list` не требует, чтобы элемент был `clickable=true` или имел content-desc'овый префикс типичный для ListItem — тащит всё подряд из диапазона.

**Почему проблема осталась после refactor-revision-use-switcher-engine (T6):** refactor убрал мусорный regex-fallback в YouTube при отсутствии кнопки «Аккаунты» (теперь возвращается `status=error, reason=accounts_button_not_found`). Но `parse_account_list` с container_y_range=1500 остался — именно он сейчас даёт мусор для IG/TT в тех сценариях, где якорь есть, а dropdown на самом деле не dropdown.

## Scope

**В scope:**
1. Фикс RC-A (server.js:3271) — удалить обращение к несуществующей `PLATFORM_TO_COLUMN`, заменить на явный whitelist IG/TT/YT.
2. Фикс RC-B:
   - Сузить `container_y_range` в `read_accounts_list` до разумного (например, ≤ 1200 px или до верхней границы экрана, если dropdown bottom-sheet — использовать высоту экрана минус нижнюю 1/3). Вынести в конфиг `UI_CONSTANTS[plat]['dropdown_max_height_px']`, дефолт 1200.
   - Ужесточить `_looks_like_username` / `_USERNAME_STOPWORDS`: добавить стоп-слова для наблюдаемых ложных попаданий (наследует из памяти — фразы типа «уведомление», «подписаться», «активность», «загрузки», «рекомендации», «главная», казахских `Есептік`, `Ұсыныстар`, арабских и др.).
   - В `parse_account_list` ввести дополнительную эвристику: токены должны иметь либо цифру, либо хотя бы один из `._-` (русские слова без таких символов отсечь); текущее `has_digit_or_sep OR len>=5` ослабить в сторону `has_digit_or_sep AND len<=40`.
3. Server-side safety-net в `/api/devices/:serial/revision/apply`: валидировать `username` regex'ом `^@?[a-zA-Z0-9][a-zA-Z0-9._-]{1,39}$` (ASCII-only; platform-specific больше не рассматриваем). Отбрасывать невалидные со `[revision/apply] invalid_username` log и включать их в ответ как `skipped_invalid: [...]`. Это страховка на случай, если скрапер всё-таки пропустит мусор.
4. Unit-тесты:
   - `test_parse_account_list_narrow_container` — dropdown y-range ограничен, фон отсечён.
   - `test_looks_like_username_rejects_russian_labels` — новые стоп-слова срабатывают.
   - `test_revision_apply_rejects_invalid_username` (nodejs — опционально, если найдём lightweight test runner; иначе `curl`-проверка в smoke).
5. Smoke: реэкзекут revision через UI на живом устройстве (phone #171 если доступен; иначе — любое phone #19-подобное устройство со стендовой факторкой). Модалка должна показать только реальные usernames; «Применить» должен вернуть `{ok:true, created:N}`.
6. Deploy в prod: применить те же патчи в `/root/.openclaw/workspace-genri/autowarm/`, коммит и `pm2 restart autowarm`.

**НЕ в scope:**
- Переписать `parse_account_list` с нуля через OCR/Vision — отдельная задача, если простой hardening не закроет.
- Политика «только YT с gmail binding», «auto-dedup по instagram_id» — не трогаем.
- Реанимация `account_packages` — таблица DROP'нута, возврата не будет.
- Локализация UI'ового текста в других языках (KZ/AR parsing) — закрываем stopwords'ами, не делаем BabelFish.

## Задачи

### T1. ✅ Расследование мусорных дампов (без кода)

**Итог:** корневая причина мусора — prod autowarm отстаёт от testbench на 4 коммита. Prod `/root/.openclaw/workspace-genri/autowarm/`:
- HEAD: `616421a feat(testbench): UI start/stop button...`
- Отсутствуют: `99220ce fix(switcher-ro): require dropdown anchor + revision dump-dir override`, `fc7a88d Merge ... iter-4`, `f0f109f fix(switcher-ro): IG Meta-Center anchors + TT own-profile guard`, `cfa50af fix(switcher-ro): TT cold-restart, YT non-usable retry, IG noise filter`.
- В проде: старый `account_revision.py` (1052 строки) с методом `_extract_username_from_ui` (regex fallback), старый `account_switcher.py` без `read_accounts_list`.
- Testbench `account_revision.py` (615 строк) использует `_RevisionPublisherShim` + `switcher.read_accounts_list`.

Значит модалка показывает мусор из-за **недеплоенного revision refactor'а**. T7 (full code-sync testbench → prod) закроет этот баг сам по себе. T3/T4/T5 — hardening поверх, защита от будущих регрессий. T2 — независимый JS regression.

Цель: убедиться, что RC-B верна, и собрать список мусорных токенов для stopwords.

- `ls -lt /tmp/autowarm_revision_dumps/RF8Y90GCWWL_* | head -30` — найти последние dropdown-дампы (их имя содержит `_profile_` или свежие timestamps).
- Прогнать через Python:
  ```python
  from adb_utils import parse_ui_dump
  from account_switcher import parse_account_list, find_anchor_bounds, ACCOUNT_LIST_ANCHORS
  xml = open('/tmp/autowarm_revision_dumps/<latest>.xml').read()
  els = parse_ui_dump(xml)
  anchor = find_anchor_bounds(els, ACCOUNT_LIST_ANCHORS['Instagram'])
  rng = (max(0, anchor[1]-1500), anchor[3]+50) if anchor else None
  for a in parse_account_list(els, rng):
      print(a.username, a.extra[:80])
  ```
- Записать мусорные токены в evidence (T6). Использовать их как seed для T3 stopwords.
- Лог: `[invest] dump=<name> anchor_y=... range=... mock_usernames=[...] garbage=[...]`.

### T2. ✅ Фикс RC-A: убрать PLATFORM_TO_COLUMN из server.js

Файл: `/home/claude-user/autowarm-testbench/server.js` (строки ~3269-3275).

**Было:**
```javascript
const platformLc = (acc.platform || '').toLowerCase();
const column = PLATFORM_TO_COLUMN[platformLc];
if (!column) {
  console.warn(`[revision/apply] skip out-of-scope platform=${acc.platform} acc=${acc.username}`);
  continue;
}
```

**Станет:**
```javascript
const platformLc = (acc.platform || '').toLowerCase();
const ALLOWED_PLATFORMS = new Set(['instagram', 'tiktok', 'youtube']);
if (!ALLOWED_PLATFORMS.has(platformLc)) {
  console.warn(`[revision/apply] skip out-of-scope platform=${acc.platform} acc=${acc.username}`);
  continue;
}
```

(Константу `ALLOWED_PLATFORMS` поднять из тела цикла — объявить один раз в начале файла рядом с другими platform-whitelist-константами; `grep -n "ALLOWED_PLATFORMS\|PLATFORM_PACKAGES" server.js` подскажет точку.)

Лог: `[revision/apply] skip out-of-scope platform=... acc=...` (формат сохраняется).

### T3. ✅ Фикс RC-B part 1: сузить container_y_range в read_accounts_list

Файл: `/home/claude-user/autowarm-testbench/account_switcher.py`, строки ~722-727.

- Заменить магическую константу 1500 на:
  ```python
  DROPDOWN_MAX_HEIGHT_PX = 1200  # bottom-sheet обычно занимает ≤ 1/2 экрана
  y_top = max(0, anchor_bounds[1] - DROPDOWN_MAX_HEIGHT_PX)
  y_bot = anchor_bounds[3] + 50
  container_y_range = (y_top, y_bot)
  ```
- Добавить sanity-check: если anchor_bounds[1] < DROPDOWN_MAX_HEIGHT_PX * 0.3 (якорь в верхней трети экрана) — это подозрительно для bottom-sheet'а, логируем WARN и **дополнительно** требуем, чтобы anchor_bounds[1] был ниже `cfg['profile_title_header_y_range'][1] + 200` (якорь не должен быть в области header'а профиля). Если якорь в подозрительной позиции → `status='error', reason='anchor_in_suspicious_position'`.
- Лог: `[switcher-ro] {plat}: dropdown y_range=(lo, hi) anchor_at={anchor_bounds} height={hi-lo}`.

Unit-тест `test_read_accounts_list_narrow_container` в `tests/test_switcher_read_only.py`:
- Fixture: XML с якорем на y=2000 (низ экрана) + «мусор» на y=300 (header)
- `read_accounts_list` должна отсечь мусор, вернуть только то, что между y=800 и y=2050.

### T4. ✅ Фикс RC-B part 2: ужесточить _USERNAME_STOPWORDS + _looks_like_username

Файл: `/home/claude-user/autowarm-testbench/account_switcher.py`, строки ~252-294.

- Расширить `_USERNAME_STOPWORDS` по результату T1 (seed-список, минимум):
  ```
  загрузки, рекомендации, подписки, активность, главная, публикация,
  публикации, сохранённое, недавнее, метки, отметки, сообщения, чат, чаты,
  поиск, популярное, избранное, лайки, комментарии, комментарий,
  поделиться, профиля, посмотреть, подписаться, подписан, подписана,
  друзья, подборка, просмотры, просмотр, история, истории, рилс, reels,
  youtube studio, shorts, ваши, твои, мои
  ```
  (Финальный список — после T1 по факту наблюдаемого мусора.)
- Ужесточить правило в `_looks_like_username`:
  ```python
  # Было: return has_digit_or_sep or len(s) >= 5
  # Стало: чистые кириллические/казахские слова без цифры/точки/дефиса — отсечь.
  has_latin = any('a' <= c <= 'z' for c in s)
  has_digit = any(c.isdigit() for c in s)
  has_sep = any(c in '._-' for c in s)
  if has_digit or has_sep:
      return True
  # Если есть ≥1 латинская буква и длина ≥4 — считаем валидным username.
  # Чисто-кириллические слова без цифр/разделителей — НЕ username (usernames
  # IG/TT/YT всегда латинница или смешанное, но редко чистая кириллица).
  return has_latin and len(s) >= 4
  ```
- Unit-тесты (`tests/test_switcher_read_only.py` или `test_account_switcher.py`):
  ```
  assert not _looks_like_username('уведомление')
  assert not _looks_like_username('подписаться')
  assert not _looks_like_username('Есептік')
  assert _looks_like_username('born.trip90')
  assert _looks_like_username('ivana.world.class')
  assert _looks_like_username('user123')
  assert _looks_like_username('abc-xyz')
  assert not _looks_like_username('активность')
  ```

### T5. ✅ Фикс RC-B part 3: server-side username validation в revision/apply

Файл: `/home/claude-user/autowarm-testbench/server.js`, функция `POST /api/devices/:serial/revision/apply` (~3193-3355).

- После `const platformLc = ...` и whitelist-check'а добавить:
  ```javascript
  const USERNAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{1,39}$/;
  const unClean = (acc.username || '').trim().replace(/^@/, '');
  if (!USERNAME_RE.test(unClean)) {
    console.warn(`[revision/apply] invalid_username platform=${platformLc} raw=${JSON.stringify(acc.username)}`);
    skipped_invalid.push({ platform: acc.platform, username: acc.username, reason: 'invalid_format' });
    continue;
  }
  ```
- Объявить `const skipped_invalid = []` перед циклом; добавить в `res.json(...)` в конце: `skipped_invalid`.
- Лог: `[revision/apply] invalid_username platform=... raw="..."`.
- (Опционально) UI на стороне `index.html` `revisionApply` после success показать:
  ```js
  if (data.skipped_invalid?.length) {
    document.getElementById('revision-success-text').textContent +=
      ` (пропущено невалидных: ${data.skipped_invalid.length})`;
  }
  ```
  Это улучшение UX, но не обязательно — основной защитный слой уже работает.

### T6. ✅ Smoke на живом устройстве

**Результат:** phone #171 (`RF8Y90GCWWL`, 268) после deploy:
- **Instagram:** `status=found accounts=['ivana.world.class', 'born.trip90']` — точные 2 аккаунта, никакого мусора.
- **TikTok:** `status=found accounts=['born']` — один валидный handle (без мусора, но без `.trip90` — current прочитан из header'а; нестрашно).
- **YouTube:** timeout 240s (не успел за smoke window; launch/navigation отдельный риск, не related to RC).

Phone #282 (`RF8Y91F8T6J`) — IG/TT на устройстве apps не стартанули: `status=error reason=launch_failed_after_aggressive_reset accounts=[]`. Правильная деградация (нет мусорного fallback'а).

Предусловие: T1-T5 закоммичены на `testbench` ветке autowarm-testbench, скрипт запускается из CLI.

- Выбрать устройство: phone #171 (`RF8Y90GCWWL`, 82.115.54.26:15037) если доступен. Иначе phone #19 или ближайшее `SELECT device_id, adb_host, adb_port FROM factory_device_numbers WHERE raspberry IS NOT NULL ORDER BY id DESC LIMIT 5;`.
- Перезапустить UI-backend (testbench-стенд): `pm2 restart autowarm-testbench` (если testbench deploy идёт через pm2 на самом стенде — см. memory `feedback_autowarm_testbench_deploy.md`).
- Открыть `https://testbench.openclaw.dev/` (или актуальный URL validator UI) → устройство → «Ревизия».
- Ожидание: в модалке в «Новые аккаунты» — только реальные usernames (латинница + цифры/точки), мусора из header'а нет.
- Нажать «Применить» → `{ok:true, created:N}` (вместо `PLATFORM_TO_COLUMN is not defined`).
- Если `skipped_invalid` не пустой — проверить в `pm2 logs` соответствующие `[revision/apply] invalid_username` записи и в evidence приложить raw-токены (они пригодятся для следующей итерации stopwords).

Лог: `[smoke] device={serial} modal_accounts=[...] apply_result={ok,created,skipped_invalid}`.

### T7. ✅ Deploy в prod autowarm

**Что выяснилось:** prod `/root/.openclaw/workspace-genri/autowarm/` был на orphan ветке `feature/testbench-iter-4-publish-polish` (HEAD=616421a), отставая от testbench на 9 коммитов (включая весь revision refactor T8 и `read_accounts_list` API). Именно это — корневая причина мусора в модалке (prod использовал старый `_extract_username_from_ui` regex fallback).

**Сделано:**
- `git checkout -b testbench --track origin/testbench` в prod dir → HEAD=025ae18.
- Проверено: `PLATFORM_TO_COLUMN` больше нет в prod server.js, `ALLOWED_PLATFORMS`/`USERNAME_RE` на месте; `account_revision.py` теперь 615 строк (новый, через `switcher.read_accounts_list`); `account_switcher.py` содержит `DROPDOWN_MAX_HEIGHT_PX=1200` и `anchor_in_suspicious_position`.
- `sudo pm2 restart autowarm` → status=online, restart #174, uptime=5s, логи чистые (обычная работа orchestrator'а/publisher'а без ReferenceError).

После успешного T6 на testbench:

- `cp` патчи T2/T3/T4/T5 в `/root/.openclaw/workspace-genri/autowarm/server.js` + `account_switcher.py`. Ручной diff перед коммитом (`diff -u /home/claude-user/autowarm-testbench/server.js /root/.openclaw/workspace-genri/autowarm/server.js` — оба сейчас identical, см. baseline проверку).
- В prod-repo:
  ```
  cd /root/.openclaw/workspace-genri/autowarm
  git add server.js account_switcher.py
  git commit -m "fix(revision): strict username filter + drop PLATFORM_TO_COLUMN"
  # post-commit hook auto-push в GenGo2/delivery-contenthunter
  sudo pm2 restart autowarm
  ```
- Проверить `pm2 logs autowarm --lines 30` — старт без ошибок, нет `ReferenceError`.
- Повторный smoke на prod UI через 1-2 минуты после restart'а.

### T8. Evidence + коммит

Evidence-файл `/home/claude-user/contenthunter/.ai-factory/evidence/revision-platform-column-and-garbage-20260423.md`:
- Корневые причины (RC-A, RC-B) со ссылками на строки server.js / account_switcher.py.
- T1 investigation output: мусорные токены из реальных дампов.
- Diff'ы T2-T5 (кратко).
- T6 smoke result (до/после скрины или текстовый вывод).
- T7 prod deploy confirmation (pm2 restart + smoke).
- Пустая ли `skipped_invalid` в проде после прогона.

Коммиты:
- `autowarm-testbench` (ветка `testbench`, push на origin): один или два коммита —
  1. `fix(revision): strict username filter + narrow dropdown container`
  2. `fix(revision/apply): drop PLATFORM_TO_COLUMN regression, add server-side username validation`
  (можно объединить в один, если diff компактный).
- `contenthunter` (main): `docs(plans+evidence): revision platform-column + garbage fix — executed T1-T8`.

## Commit Plan

8 задач → 3 коммит-чекпоинта:

| Commit | После задач | Репо | Сообщение |
|---|---|---|---|
| 1 | T5 | autowarm-testbench (testbench) | `fix(revision): strict username filter + drop PLATFORM_TO_COLUMN server-side` |
| 2 | T7 | prod autowarm (GenGo2/delivery-contenthunter) | `fix(revision): sync strict-filter fix from testbench` |
| 3 | T8 | contenthunter (main) | `docs(plans+evidence): revision platform-column + garbage fix` |

## Риски

- **R1 — слишком строгий filter отсечёт валидные username'ы.** Некоторые IG/TT-аккаунты могут быть чисто-кириллические (редко, но бывают). Миттиг: T4 оставляет `has_digit_or_sep → True` ветку — любой username с цифрой или `._-` проходит независимо от алфавита. Смотреть в `skipped_invalid` проде после прогона — если больше 0, читать raw и расширять regex при необходимости.
- **R2 — `DROPDOWN_MAX_HEIGHT_PX=1200` может не хватить на планшетах / больших экранах.** Миттиг: сделать значение per-platform в `UI_CONSTANTS`; для начала — единое 1200, итерировать по факту.
- **R3 — `pm2 restart autowarm` может уронить стенд на время restart'а.** Мерж не в прайм-тайм; restart ≤2 сек; health-check после. Fallback: `git revert` последнего коммита + еще один restart.
- **R4 — деплой в prod autowarm через auto-push hook может задеть другие файлы.** Коммит делается вручную с явным `git add <files>`, не `git add -A`. Миттиг гарантирует, что в коммит попадут только server.js и account_switcher.py.
- **R5 — T6 smoke на #171 не воспроизведётся** (phone offline, TT залип в чужом профиле — см. memory). Fallback: запуск на другом устройстве из factory_device_numbers; цель T6 — убедиться что (а) модалка без мусора (на ЛЮБОМ устройстве с залогиненными аккаунтами) и (б) «Применить» не даёт `ReferenceError`.

## Rollback

- Commit 1: `git revert` вернёт prev behaviour (модалка с мусором, но и крэш `PLATFORM_TO_COLUMN` тоже), это временно допустимо если новый filter слишком строгий.
- Commit 2: отдельный `git revert` в prod dir + `pm2 restart`. Post-commit hook автоматом пушнёт revert.
- Commit 3: докс-only, никогда не нуждается в revert.

## Дальше

Исполнять через `/aif-implement`. Порядок: T1 → T2 → T3 → T4 → T5 → commit #1 → T6 → T7 → commit #2 → T8 → commit #3.
