# WP #126 Фаза 2b — client (validator): мультивыбор на 3 страницах + бэкенд-агрегация

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Добавить мультивыбор проектов (OR / суммирование) на 3 страницы клиентского кабинета — **Публикации, Аккаунты, Аналитика**. Бэкенд учится принимать `X-Project-Ids` (CSV целочисленных id) и агрегировать. Дашборд НЕ трогаем (у него уже single/«Все проекты»); brand/schemes/contract — одиночные (только 2a). Решение пользователя 2026-05-25: эти 3 страницы; аналитика — суммирование (combined).

**Architecture:** Расширяем `SearchableSelect.vue` режимом `multiple` (массив в `v-model`, чекбоксы, событие `change` при ЗАКРЫТИИ всплывашки — чтобы серверный запрос шёл один раз, а не на каждый чек). Стор `project.ts` получает helper `projectIdsHeader(ids)` → `{ 'X-Project-Ids': ids.join(',') }` (id числовые — comma-safe). Каждая из 3 страниц держит локальный `selectedProjectIds: number[]` (инициализируется из `selectedProjectId`), биндит multi-`SearchableSelect`, на `change` грузит данные с `X-Project-Ids`. Бэкенд: per-router `_resolve_project_ids()` + `WHERE ... = ANY(:pids)`; аккаунты — объединение `get_project_accounts` по каждому pid (переиспользуем протестированный single-путь). Обратная совместимость: один проект → `pids=[pid]`.

**Tech Stack:** Vue 3 + TS + Tailwind + Vitest (фронт); FastAPI + SQLAlchemy + Postgres + pytest (бэк). ⚠ **Бэкенд НЕ запускается в текущем окружении (нет БД) — серверные правки только под review + тип/синтаксис; обязателен DB-смоук человеком.**

**Спека:** §6; **база:** ЛОКАЛЬНЫЙ main validator (HEAD `fcb0522`, содержит 2a — origin это НЕ имеет). Worktree контроллер создаст off локального main.

---

## File Structure

| Файл | Действие | Что |
|---|---|---|
| `frontend/src/components/SearchableSelect.vue` | Modify | + `multiple` режим (чекбоксы, массив v-model, `change` на close). |
| `frontend/src/components/__tests__/SearchableSelect.spec.ts` | Create | Vitest: single emit + multi emit-on-close. |
| `frontend/src/stores/project.ts` | Modify | + `projectIdsHeader(ids: number[])`. |
| `frontend/src/pages/client/PublicationsPage.vue` | Modify | multi: локальный `selectedProjectIds`, multi-select, `X-Project-Ids` в фетче. |
| `frontend/src/pages/client/AccountsPage.vue` | Modify | то же. |
| `frontend/src/pages/client/AnalyticsPage.vue` | Modify | то же (summary + top-posts). |
| `backend/src/routers/accounts.py` | Modify | `_resolve_project_ids` + union `get_project_accounts` по pids. |
| `backend/src/routers/analytics.py` | Modify | `_resolve_project_ids` + `= ANY(:pids)` в publications/summary/top-posts. |

---

## Task 1: SearchableSelect.vue — режим `multiple` + spec

**Files:** Modify `frontend/src/components/SearchableSelect.vue`; Create `frontend/src/components/__tests__/SearchableSelect.spec.ts`

- [ ] **Step 1: Падающий компонентный тест** — `frontend/src/components/__tests__/SearchableSelect.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SearchableSelect from '../SearchableSelect.vue'

const opts = [{ value: 1, label: 'Аквабрайт' }, { value: 2, label: 'Бест' }, { value: 3, label: 'Парфюмерия' }]

describe('SearchableSelect', () => {
  it('single: клик по опции эмитит update:modelValue и change', async () => {
    const w = mount(SearchableSelect, { props: { modelValue: 0, options: opts } })
    await w.find('button').trigger('click')              // open
    const rows = w.findAll('.ss-opt')
    await rows[0].trigger('click')                        // pick first (sorted: Аквабрайт)
    expect(w.emitted('update:modelValue')?.[0]).toEqual([1])
    expect(w.emitted('change')).toBeTruthy()
  })

  it('multiple: тоггл копит выбор, change эмитится при закрытии', async () => {
    const w = mount(SearchableSelect, { props: { modelValue: [], options: opts, multiple: true } })
    await w.find('button').trigger('click')              // open
    const rows = w.findAll('.ss-opt')
    await rows[0].trigger('click')                        // toggle Аквабрайт (value 1)
    await rows[1].trigger('click')                        // toggle Бест (value 2)
    expect(w.emitted('change')).toBeFalsy()              // ещё не закрыли
    const last = w.emitted('update:modelValue')?.at(-1)
    expect(last).toEqual([[1, 2]])
    document.dispatchEvent(new MouseEvent('mousedown'))   // click-outside → close
    await w.vm.$nextTick()
    expect(w.emitted('change')).toBeTruthy()             // change на close
  })
})
```

(`.ss-opt` — класс строки опции; добавить его в шаблон в Step 2.)

- [ ] **Step 2: Запустить — упадёт** (нет `multiple`/`.ss-opt`/`change`)

Run: `cd <worktree>/frontend && npx vitest run src/components/__tests__/SearchableSelect.spec.ts 2>&1 | tail -10`

- [ ] **Step 3: Расширить компонент.** Полное новое содержимое `frontend/src/components/SearchableSelect.vue`:

```vue
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { sortOptionsByLabel, filterOptions, type SsOption } from '@/utils/projectSort'

type Val = number | string
const props = withDefaults(defineProps<{
  modelValue: Val | Val[]
  options: SsOption[]
  placeholder?: string
  multiple?: boolean
}>(), { placeholder: 'Выберите…', multiple: false })

const emit = defineEmits<{
  (e: 'update:modelValue', v: Val | Val[]): void
  (e: 'change'): void
}>()

const open = ref(false)
const query = ref('')
const rootEl = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)

const selectedArr = computed<Val[]>(() => Array.isArray(props.modelValue) ? props.modelValue : (props.modelValue === '' || props.modelValue === 0 || props.modelValue == null ? [] : [props.modelValue]))
const filtered = computed(() => filterOptions(sortOptionsByLabel(props.options), query.value))
function isSelected(v: Val) { return selectedArr.value.some(x => String(x) === String(v)) }
const triggerLabel = computed(() => {
  const sel = selectedArr.value
  if (sel.length === 0) return props.placeholder
  if (props.multiple && sel.length > 1) return `Выбрано: ${sel.length}`
  const o = (props.options || []).find(x => String(x.value) === String(sel[0]))
  return o ? o.label : String(sel[0])
})

function openPop() { open.value = true; query.value = ''; requestAnimationFrame(() => searchEl.value?.focus()) }
function close() {
  if (!open.value) return
  open.value = false
  if (props.multiple) emit('change')      // multi: применяем при закрытии
}
function toggle() { open.value ? close() : openPop() }

function pick(o: SsOption) {
  if (props.multiple) {
    const cur = selectedArr.value.map(String)
    const v = String(o.value)
    const next = cur.includes(v) ? selectedArr.value.filter(x => String(x) !== v) : [...selectedArr.value, o.value]
    emit('update:modelValue', next)        // обновляем v-model, НЕ закрываем
  } else {
    emit('update:modelValue', o.value)
    emit('change')
    close()
  }
}

function onDocMouseDown(e: MouseEvent) { if (!rootEl.value || !rootEl.value.contains(e.target as Node)) close() }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
onMounted(() => { document.addEventListener('mousedown', onDocMouseDown); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('mousedown', onDocMouseDown); document.removeEventListener('keydown', onKey) })
</script>

<template>
  <div ref="rootEl" class="relative inline-block w-full">
    <button type="button" @click="toggle"
      class="flex w-full items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300">
      <span class="truncate" :class="{ 'text-gray-400': selectedArr.length === 0 }">{{ triggerLabel }}</span>
      <span class="text-gray-400">▾</span>
    </button>
    <div v-if="open" class="absolute z-50 mt-1 w-full min-w-[220px] rounded-xl border border-gray-200 bg-white shadow-lg">
      <input ref="searchEl" v-model="query" placeholder="поиск…"
        class="w-full rounded-t-xl border-b border-gray-100 px-3 py-2 text-sm focus:outline-none" />
      <div class="max-h-60 overflow-y-auto py-1">
        <button v-for="o in filtered" :key="o.value" type="button" @click="pick(o)"
          class="ss-opt flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-indigo-50">
          <input v-if="multiple" type="checkbox" :checked="isSelected(o.value)" tabindex="-1" class="pointer-events-none" />
          <span v-else class="w-3 text-indigo-600">{{ isSelected(o.value) ? '✓' : '' }}</span>
          <span class="truncate">{{ o.label }}</span>
        </button>
        <div v-if="!filtered.length" class="px-3 py-2 text-center text-sm text-gray-400">ничего не найдено</div>
      </div>
    </div>
  </div>
</template>
```

⚠ Single-режим сохраняет прежний контракт 2a: `update:modelValue` на pick + теперь ещё `change` (2a-страницы используют `@update:model-value` — они продолжат работать; `change` им просто не слушается).

- [ ] **Step 4: Запустить — пройдёт** (2 теста)

Run: `cd <worktree>/frontend && npx vitest run src/components/__tests__/SearchableSelect.spec.ts 2>&1 | tail -10`
Expected: 2 passed.

- [ ] **Step 5: Регресс 2a util-теста + тип-чек компонента**

Run: `npx vitest run src/utils/__tests__/projectSort.spec.ts 2>&1 | grep -E "Tests "; npx vue-tsc --noEmit 2>&1 | grep -i SearchableSelect || echo "no SearchableSelect type errors"`

- [ ] **Step 6: Коммит**

```bash
cd <worktree>
git add frontend/src/components/SearchableSelect.vue frontend/src/components/__tests__/SearchableSelect.spec.ts
git commit -m "feat(wp126-2b): SearchableSelect — режим multiple (массив v-model, change на close) + spec"
```

---

## Task 2: Стор — helper `projectIdsHeader`

**Files:** Modify `frontend/src/stores/project.ts`

- [ ] **Step 1:** Внутри `useProjectStore`, рядом с `projectHeaders`, добавить функцию и вернуть её из стора:

Найти:
```ts
  function projectHeaders(): Record<string, string> {
    const h: Record<string, string> = {}
    if (selectedProjectId.value) {
      h['X-Project-Id'] = String(selectedProjectId.value)
    }
    return h
  }
```
Заменить на:
```ts
  function projectHeaders(): Record<string, string> {
    const h: Record<string, string> = {}
    if (selectedProjectId.value) {
      h['X-Project-Id'] = String(selectedProjectId.value)
    }
    return h
  }

  // WP#126-2b: заголовок для мультивыбора проектов (id числовые → CSV, comma-safe).
  // Пустой список → пустой объект (страница покажет gate «выберите проект»).
  function projectIdsHeader(ids: number[]): Record<string, string> {
    const list = (ids || []).filter(Boolean)
    return list.length ? { 'X-Project-Ids': list.join(',') } : {}
  }
```
И в `return { ... }` добавить `projectIdsHeader`.

- [ ] **Step 2:** Тип-чек: `cd <worktree>/frontend && npx vue-tsc --noEmit 2>&1 | grep -i "stores/project" || echo "ok"`

- [ ] **Step 3: Коммит**

```bash
git add frontend/src/stores/project.ts
git commit -m "feat(wp126-2b): projectStore.projectIdsHeader (X-Project-Ids)"
```

---

## Task 3: Backend — `_resolve_project_ids` + ANY (accounts + analytics)

⚠ Бэкенд НЕ запускается локально (нет БД). Правки зеркалят существующий single-паттерн + reference `/schedule/all` (`.in_()`). Проверка — `python -c "import ast; ast.parse(open(f).read())"` (синтаксис) + review; runtime — DB-смоук человеком.

**Files:** Modify `backend/src/routers/accounts.py`, `backend/src/routers/analytics.py`

- [ ] **Step 1: accounts.py — добавить `_resolve_project_ids` (после `_resolve_project_id`, ~line 19)**

После функции `_resolve_project_id` вставить:
```python
def _resolve_project_ids(
    current_user: ValidatorUser,
    header_project_ids: str | None = None,
    header_project_id: int | None = None,
) -> list[int]:
    """Список project_id из X-Project-Ids (CSV) или одиночный X-Project-Id, с учётом RBAC клиента."""
    ids: list[int] = []
    if header_project_ids:
        for part in str(header_project_ids).split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.append(int(part))
    if not ids:
        single = _resolve_project_id(current_user, header_project_id)
        return [single] if single else []
    if current_user.role == UserRole.client:
        # клиент видит только свой проект
        return [current_user.project_id] if current_user.project_id else []
    return ids
```

- [ ] **Step 2: accounts.py — `list_accounts` принимает `X-Project-Ids`, объединяет**

Найти:
```python
@router.get("")
async def list_accounts(
    current_user: ValidatorUser = Depends(get_current_user),
    x_project_id: Optional[int] = Header(None, alias="X-Project-Id"),
    db: AsyncSession = Depends(get_db),
):
    project_id = _resolve_project_id(current_user, x_project_id)
    accounts = await get_project_accounts(project_id, db)
    return {"project_id": project_id, "accounts": accounts}
```
Заменить на:
```python
@router.get("")
async def list_accounts(
    current_user: ValidatorUser = Depends(get_current_user),
    x_project_id: Optional[int] = Header(None, alias="X-Project-Id"),
    x_project_ids: Optional[str] = Header(None, alias="X-Project-Ids"),
    db: AsyncSession = Depends(get_db),
):
    pids = _resolve_project_ids(current_user, x_project_ids, x_project_id)
    # Мультипроект: объединяем аккаунты по каждому проекту (переиспользуем single-путь).
    accounts: list = []
    for pid in pids:
        accounts.extend(await get_project_accounts(pid, db))
    return {"project_ids": pids, "project_id": pids[0] if len(pids) == 1 else None, "accounts": accounts}
```

- [ ] **Step 3: analytics.py — добавить `_resolve_project_ids` (после `_resolve_project_id`, ~line 30)**

Вставить ту же функцию `_resolve_project_ids`, что в Step 1 (идентичную).

- [ ] **Step 4: analytics.py — `client_publications`: header + ANY**

В сигнатуре (после `x_project_id: ... Header(None, alias="X-Project-Id"),` ~line 457) добавить:
```python
    x_project_ids: Optional[str] = Header(None, alias="X-Project-Ids"),
```
Заменить (~line 467):
```python
    pid = _resolve_project_id(current_user, x_project_id)
```
на:
```python
    pids = _resolve_project_ids(current_user, x_project_ids, x_project_id)
```
Заменить (~line 520) `WHERE fpa.project_id = :pid` на `WHERE fpa.project_id = ANY(:pids)`.
И в вызове `db.execute(text(...), {...})` для этого запроса заменить параметр `"pid": pid` на `"pids": pids` (найти по соседству; если pid передаётся в нескольких местах одного запроса — заменить все).

- [ ] **Step 5: analytics.py — `client_analytics_summary`: header + ANY ×4**

В сигнатуре (~line 192) добавить `x_project_ids: Optional[str] = Header(None, alias="X-Project-Ids"),`.
Заменить (~line 200) `pid = _resolve_project_id(...)` → `pids = _resolve_project_ids(current_user, x_project_ids, x_project_id)`.
Заменить ВСЕ четыре `WHERE fpa.project_id = :pid` (231, 272, 292, 309) → `WHERE fpa.project_id = ANY(:pids)` (используй Edit `replace_all: true` по строке `WHERE fpa.project_id = :pid` ВНУТРИ этой функции — но т.к. строка встречается и в других функциях, делать осторожно: заменять по одному с уникальным контекстом ИЛИ заменить во всём файле разом в Step 7 после смены всех `pid`→`pids`).
Заменить параметры `"pid": pid` → `"pids": pids` в каждом `db.execute` этой функции.

- [ ] **Step 6: analytics.py — `client_top_posts`: header + ANY**

Сигнатура (~line 378) + `pid = _resolve_project_id` (~383) → `pids = _resolve_project_ids(...)`; `WHERE fpa.project_id = :pid` (~418) → `= ANY(:pids)`; параметр `"pid": pid` → `"pids": pids`.

- [ ] **Step 7: Унифицировать замену и проверить**

После правок убедиться, что в трёх изменённых функциях НЕ осталось `:pid`/`"pid"` (только `:pids`/`"pids"`), а `_resolve_project_id` (единичный) больше не вызывается в них:
```bash
cd <worktree>/backend
grep -n "fpa.project_id = :pid\b" src/routers/analytics.py || echo "no single :pid left in WHERE (good)"
python3 -c "import ast; ast.parse(open('src/routers/analytics.py').read()); ast.parse(open('src/routers/accounts.py').read()); print('syntax OK')"
```
Expected: нет одиночных `:pid` в WHERE; `syntax OK`.

⚠ ВАЖНО: проверить, что параметр в `db.execute(text(q), params)` называется `pids` И в SQL `ANY(:pids)`, И в словаре `{"pids": pids, ...}`. Несоответствие имени = runtime-ошибка (не ловится синтаксисом). На review сверить каждый из 6 запросов: SQL-плейсхолдер ↔ ключ словаря.

- [ ] **Step 8: Коммит**

```bash
cd <worktree>
git add backend/src/routers/accounts.py backend/src/routers/analytics.py
git commit -m "feat(wp126-2b): backend accounts/analytics принимают X-Project-Ids (= ANY(:pids), совместимо)"
```

---

## Task 4: Frontend — 3 страницы в multi

Каждая страница: локальный `selectedProjectIds` (init из `selectedProjectId`), multi-`SearchableSelect`, фетчи с `projectStore.projectIdsHeader(selectedProjectIds)`.

**Files:** Modify `PublicationsPage.vue`, `AccountsPage.vue`, `AnalyticsPage.vue`

Канонический паттерн (применить к каждой, прочитав точный код):
1. `import { ref }` уже есть; добавить локальный стейт: `const selectedProjectIds = ref<number[]>([])`.
2. Инициализация: там, где сейчас устанавливается стартовый проект (или в `onMounted`/`watch` по `selectedProjectId`), синхронизировать: `selectedProjectIds.value = projectStore.selectedProjectId ? [projectStore.selectedProjectId] : []`.
3. Заменить `<SearchableSelect v-model="selectedProjectId" :options="projectOptions" placeholder="…" @update:model-value="onProjectChange" />` (из 2a) на:
   `<SearchableSelect v-model="selectedProjectIds" :options="projectOptions" multiple placeholder="Выберите проект(ы)…" @change="onProjectsChange" />`
4. Добавить `function onProjectsChange() { load() }` (имя функции загрузки на странице — `load`/`loadData`/`loadAccounts`; посмотреть существующий `onProjectChange`).
5. В фетч-вызовах заменить `headers: projectStore.projectHeaders()` на `headers: projectStore.projectIdsHeader(selectedProjectIds.value)`.
6. Gate пустого выбора: где было `v-if="!selectedProjectId"` (нет проекта) — заменить на `v-if="!selectedProjectIds.length"`.

- [ ] **Step 1: PublicationsPage.vue** — фетч `/analytics/client/publications` (~285). Коммит `feat(wp126-2b): Публикации — мультивыбор проектов`.
- [ ] **Step 2: AccountsPage.vue** — фетч `/accounts` (~362). Коммит `feat(wp126-2b): Аккаунты — мультивыбор проектов`.
- [ ] **Step 3: AnalyticsPage.vue** — фетчи `/analytics/client/summary` (~505) и `/analytics/client/top-posts` (~526). Коммит `feat(wp126-2b): Аналитика — мультивыбор проектов`.

После каждой: `npx vue-tsc --noEmit 2>&1 | grep -i "<Page>.vue" || echo ok`.

---

## Task 5: Смоук, ревью, мерж

- [ ] **Step 1: Vitest (наши + существующие spec'и)**

Run: `cd <worktree>/frontend && npx vitest run src/utils/__tests__/projectSort.spec.ts src/components/__tests__/SearchableSelect.spec.ts src/components/calendar/__tests__/SlotCard.spec.ts 2>&1 | grep -E "Test Files|Tests "`
Expected: все проходят (projectSort 3 + SearchableSelect 2 + SlotCard 6).

- [ ] **Step 2: Тип-чек**

Run: `npx vue-tsc --noEmit 2>&1 | tail -15`
Expected: нет НОВЫХ ошибок в наших файлах.

- [ ] **Step 3: Backend синтаксис + соответствие плейсхолдеров**

Run:
```bash
cd <worktree>/backend
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['src/routers/accounts.py','src/routers/analytics.py']]; print('syntax OK')"
grep -n "ANY(:pids)" src/routers/analytics.py
```
Expected: `syntax OK`; `ANY(:pids)` в 6 местах (publications 1, summary 4, top-posts 1).

- [ ] **Step 4: Финальный код-ревью** — особое внимание: соответствие SQL `:pids` ↔ ключ словаря `pids` в КАЖДОМ из 6 запросов analytics; RBAC клиента в `_resolve_project_ids`; gate пустого выбора на 3 страницах.

- [ ] **Step 5: Визуальный + DB смоук (за человеком)** — на 3 страницах под admin/manager: мультиселект, отметить 2+ проекта → данные объединяются/суммируются (по закрытию всплывашки, один запрос); один проект → как раньше; клиент видит только свой. Дашборд/brand/schemes/contract не изменились.

- [ ] **Step 6: Мерж в локальный main validator** (по аналогии с 2a: ff-merge, vitest, cleanup worktree+ветка).

---

## Self-Review (выполнено автором)

- **Скоуп (решение 2026-05-25):** мульти на Публикации/Аккаунты/Аналитика; дашборд/brand/schemes/contract не трогаем. ✓
- **Аналитика = суммирование:** `= ANY(:pids)` поверх существующих SUM-агрегатов даёт combined-метрики; by_platform/top — по объединению. ✓
- **Обратная совместимость:** `_resolve_project_ids` без `X-Project-Ids` → `[single]`; `= ANY(:pids)` с одним элементом = прежнее поведение; single-страницы (2a) не тронуты, `change`-событие компонента им не мешает. ✓
- **Аккаунты:** объединение через повтор `get_project_accounts` (без переписывания сложного service-запроса на один api_name) — низкий риск. ✓
- **Apply-on-close:** multi эмитит `change` при закрытии → один серверный запрос на выбор, не на каждый чек. ✓
- **Риск (НЕ верифицируемо локально):** имя SQL-параметра `:pids` ↔ ключ словаря — главный источник runtime-ошибок; Step 7/3 грепом + ревью по каждому из 6 запросов. ⚠ DB-смоук обязателен.
- **Comma-safe:** `X-Project-Ids` = CSV целочисленных id (не имён) → запятая невозможна. ✓
