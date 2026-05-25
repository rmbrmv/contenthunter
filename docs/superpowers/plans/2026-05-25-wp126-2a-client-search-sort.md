# WP #126 Фаза 2a — client (validator): SearchableSelect + поиск/сортировка на 7 страницах

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Заменить нативные `<select>` селекторы проекта на переиспользуемый Vue-компонент `SearchableSelect` с полем поиска и единой алфавитной сортировкой — на всех 7 страницах клиентского кабинета. Одиночный выбор, без изменений бэкенда. Закрывает поиск+сортировку для client (зеркало Фазы 1a в delivery).

**Architecture:** Чистые функции сортировки/фильтра — `frontend/src/utils/projectSort.ts` (тестируются vitest). Компонент `frontend/src/components/SearchableSelect.vue` (Vue 3 `<script setup lang="ts">`, Tailwind, без UI-либ): триггер + всплывашка с поиском, single-select, `v-model`. Мультивыбор НЕ здесь (Фаза 2b расширит компонент). Каждая страница: `import SearchableSelect`, computed `projectOptions` из стора, `<SearchableSelect v-model="selectedProjectId" :options="projectOptions" @update:model-value="onProjectChange" />`.

**Tech Stack:** Vue 3.4 + TypeScript + Tailwind, Vite, Vitest (`npm test` = `vitest run`). Repo: `/home/claude-user/validator-contenthunter/`.

**Спека:** `docs/superpowers/specs/2026-05-25-wp126-search-sort-filters-design.md` (§6).

**Важно:**
- Все правки в worktree validator: `/home/claude-user/validator-contenthunter-feat-wp126-2a-<...>` (контроллер создаст).
- Проектный alias: проверить `vite.config`/`tsconfig` — если есть `@ → src`, использовать `@/...`; иначе относительные пути. Матчить существующий стиль импортов в файле.
- `npm run build` имеет postbuild-хук (копирует в `/var/www/validator/`) — НЕ запускать build на worktree; только `npm test` (vitest) и `vue-tsc` при наличии.
- 6 страниц используют `projects` (стор) + placeholder `:value="0"`; dashboard — `allProjects` + `value=""` внутри `<template v-if="viewMode === 'single'">`. Сохранить источник опций каждой страницы.

---

## File Structure

| Файл | Действие | Ответственность |
|---|---|---|
| `frontend/src/utils/projectSort.ts` | Create | `compareLabels`, `sortOptionsByLabel`, `filterOptions` (чистые, без Vue). |
| `frontend/src/utils/__tests__/projectSort.test.ts` | Create | Vitest-тесты util. |
| `frontend/src/components/SearchableSelect.vue` | Create | Single-select searchable dropdown (`v-model`, `:options`, `:placeholder`). |
| 7 client-страниц | Modify | import + computed `projectOptions` + замена `<select>` на `<SearchableSelect>`. |

---

## Task 1: Util сортировки/фильтра + тесты (TDD)

**Files:** Create `frontend/src/utils/projectSort.ts`, `frontend/src/utils/__tests__/projectSort.test.ts`

- [ ] **Step 1: Падающий тест** — `frontend/src/utils/__tests__/projectSort.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { compareLabels, sortOptionsByLabel, filterOptions } from '../projectSort'

describe('projectSort', () => {
  it('compareLabels: RU, регистронезависимо, числа натурально', () => {
    expect(compareLabels('Аквабрайт', 'Бест Клиник')).toBeLessThan(0)
    expect(compareLabels('бест', 'Аквабрайт')).toBeGreaterThan(0)
    expect(Math.sign(compareLabels('тел 2', 'тел 10'))).toBe(-1)
  })
  it('sortOptionsByLabel: по label, не мутирует', () => {
    const input = [{ value: 3, label: 'Балтамбер' }, { value: 1, label: 'Аквабрайт' }, { value: 2, label: 'бест' }]
    expect(sortOptionsByLabel(input).map(o => o.label)).toEqual(['Аквабрайт', 'Балтамбер', 'бест'])
    expect(input[0].label).toBe('Балтамбер')
  })
  it('filterOptions: подстрока регистронезависимо; пустой → все', () => {
    const opts = [{ value: 1, label: 'Парфюмерия' }, { value: 2, label: 'Аквабрайт' }]
    expect(filterOptions(opts, 'парф').map(o => o.value)).toEqual([1])
    expect(filterOptions(opts, '  ').map(o => o.value)).toEqual([1, 2])
  })
})
```

- [ ] **Step 2: Запустить — упадёт** (модуль не найден)

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/utils/__tests__/projectSort.test.ts`
Expected: FAIL (cannot resolve `../projectSort`).

- [ ] **Step 3: Реализовать `frontend/src/utils/projectSort.ts`:**

```ts
// projectSort.ts — чистые функции для SearchableSelect (WP #126). Без Vue/DOM.
export interface SsOption { value: number | string; label: string }

// RU-локаль, регистронезависимо, натуральный числовой порядок.
export function compareLabels(a: string, b: string): number {
  return String(a).localeCompare(String(b), 'ru', { sensitivity: 'base', numeric: true })
}

// Сортировка опций по label (копия, вход не мутируется).
export function sortOptionsByLabel(options: SsOption[]): SsOption[] {
  return [...(options || [])].sort((x, y) => compareLabels(x.label, y.label))
}

// Фильтр по подстроке query в label (регистронезависимо). Пустой/пробельный query → все.
export function filterOptions(options: SsOption[], query: string): SsOption[] {
  const q = String(query || '').trim().toLowerCase()
  if (!q) return [...(options || [])]
  return (options || []).filter(o => String(o.label).toLowerCase().includes(q))
}
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/utils/__tests__/projectSort.test.ts`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/utils/projectSort.ts frontend/src/utils/__tests__/projectSort.test.ts
git commit -m "feat(wp126-2a): projectSort util (compare/sort/filter) + vitest"
```

---

## Task 2: Компонент `SearchableSelect.vue`

**Files:** Create `frontend/src/components/SearchableSelect.vue`

- [ ] **Step 1: Создать компонент**

```vue
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { sortOptionsByLabel, filterOptions, type SsOption } from '@/utils/projectSort'

const props = withDefaults(defineProps<{
  modelValue: number | string
  options: SsOption[]
  placeholder?: string
}>(), { placeholder: 'Выберите…' })

const emit = defineEmits<{ (e: 'update:modelValue', v: number | string): void }>()

const open = ref(false)
const query = ref('')
const rootEl = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)

const filtered = computed(() => filterOptions(sortOptionsByLabel(props.options), query.value))
const triggerLabel = computed(() => {
  const o = (props.options || []).find(x => String(x.value) === String(props.modelValue))
  return o ? o.label : props.placeholder
})
function isSelected(v: number | string) { return String(v) === String(props.modelValue) }

function openPop() { open.value = true; query.value = ''; requestAnimationFrame(() => searchEl.value?.focus()) }
function close() { open.value = false }
function toggle() { open.value ? close() : openPop() }
function pick(o: SsOption) { emit('update:modelValue', o.value); close() }

function onDocMouseDown(e: MouseEvent) { if (rootEl.value && !rootEl.value.contains(e.target as Node)) close() }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
onMounted(() => { document.addEventListener('mousedown', onDocMouseDown); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('mousedown', onDocMouseDown); document.removeEventListener('keydown', onKey) })
</script>

<template>
  <div ref="rootEl" class="relative inline-block w-full">
    <button type="button" @click="toggle"
      class="flex w-full items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300">
      <span class="truncate" :class="{ 'text-gray-400': !modelValue }">{{ triggerLabel }}</span>
      <span class="text-gray-400">▾</span>
    </button>
    <div v-if="open" class="absolute z-50 mt-1 w-full min-w-[220px] rounded-xl border border-gray-200 bg-white shadow-lg">
      <input ref="searchEl" v-model="query" placeholder="поиск…"
        class="w-full rounded-t-xl border-b border-gray-100 px-3 py-2 text-sm focus:outline-none" />
      <div class="max-h-60 overflow-y-auto py-1">
        <button v-for="o in filtered" :key="o.value" type="button" @click="pick(o)"
          class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-indigo-50">
          <span class="w-3 text-indigo-600">{{ isSelected(o.value) ? '✓' : '' }}</span>
          <span class="truncate">{{ o.label }}</span>
        </button>
        <div v-if="!filtered.length" class="px-3 py-2 text-center text-sm text-gray-400">ничего не найдено</div>
      </div>
    </div>
  </div>
</template>
```

⚠️ Проверить alias `@`: `grep -n "@/" frontend/src/**/*.vue` или `tsconfig.json` `paths`. Если `@` не настроен — заменить импорт на относительный `../utils/projectSort`.

- [ ] **Step 2: Тип-чек/сборка компонента (без полного build)**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit 2>&1 | grep -i "SearchableSelect\|projectSort" || echo "no type errors in new files"`
Expected: нет ошибок по новым файлам. (Если `vue-tsc` ругается на не связанные с задачей файлы — игнорировать, смотреть только наши.)

- [ ] **Step 3: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/components/SearchableSelect.vue
git commit -m "feat(wp126-2a): SearchableSelect.vue (single-select searchable dropdown)"
```

---

## Task 3: Заменить `<select>` на `<SearchableSelect>` на 7 страницах

Канонический паттерн (для каждой страницы):
1. В `<script setup>` добавить `import SearchableSelect from '@/components/SearchableSelect.vue'` (или относительный путь, как принято в файле) и `import { computed }` (если ещё нет).
2. Добавить computed-список опций: `const projectOptions = computed(() => projects.value.map(p => ({ value: p.id, label: p.project })))`. На dashboard источник — `allProjects` (не `projects`).
3. Заменить блок `<select v-model="selectedProjectId" @change="onProjectChange" class="...">...</select>` на:
   `<SearchableSelect v-model="selectedProjectId" :options="projectOptions" placeholder="Выберите проект…" @update:model-value="onProjectChange" class="min-w-[250px]" />`
   (на dashboard сохранить обёртку `<template v-if="viewMode === 'single'">` и `flex-1`-ширину; placeholder «— Выберите проект —».)

`@update:model-value` гарантирует вызов `onProjectChange` ПОСЛЕ обновления `selectedProjectId` (v-model отрабатывает первым).

Каждый шаг: прочитать текущий `<select>`-блок страницы, заменить точно, прогнать vue-tsc по файлу, коммит.

- [ ] **Step 1: PublicationsPage.vue** (`pages/client/PublicationsPage.vue`, select ~7-11, источник `projects`) — заменить, добавить import + `projectOptions`. Коммит: `feat(wp126-2a): Публикации — SearchableSelect`.
- [ ] **Step 2: AccountsPage.vue** (select ~7-11, `projects`) — аналогично. Коммит.
- [ ] **Step 3: AnalyticsPage.vue** (select ~7-11, `projects`) — аналогично. Коммит.
- [ ] **Step 4: BrandPage.vue** (select ~8-12, `projects`) — аналогично (остаётся одиночным и в 2b). Коммит.
- [ ] **Step 5: SchemesPage.vue** (select ~42-47, `projects`) — аналогично. Коммит.
- [ ] **Step 6: ContractPage.vue** (select ~7-11, `projects`) — аналогично. Коммит.
- [ ] **Step 7: ClientDashboard.vue** (select ~48-57 внутри `<template v-if="viewMode === 'single'">`, источник `allProjects`, placeholder «— Выберите проект —») — `const projectOptions = computed(() => allProjects.value.map(p => ({ value: p.id, label: p.project })))`. Заменить только `<select>` (обёртку `v-if` и соседний `<span>` оставить). Коммит: `feat(wp126-2a): Дашборд — SearchableSelect`.

После каждой замены:
Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit 2>&1 | grep -i "<имя файла>" || echo "ok"`

---

## Task 4: Смоук и верификация

- [ ] **Step 1: Vitest полностью**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npm test 2>&1 | tail -25`
Expected: `projectSort.test.ts` (3) проходит; существующие spec'и (slotStatus, routes, UploadModal, SlotCard, ProjectPublishModeCell) не сломаны.

- [ ] **Step 2: Тип-чек проекта**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: нет НОВЫХ ошибок типов в `SearchableSelect.vue`/`projectSort.ts`/7 страницах (pre-existing ошибки в несвязанных файлах, если есть, — не наши).

- [ ] **Step 3: Нет осиротевших `<select`-селекторов проекта**

Run: `cd /home/claude-user/validator-contenthunter && grep -rn 'v-model="selectedProjectId"' frontend/src/pages/client/ | grep '<select' || echo "no native project selects left (good)"`
Expected: пусто (все 7 заменены).

- [ ] **Step 4: Визуальный смоук (за человеком)**

На каждой из 7 страниц (под admin/manager): селектор проекта — кнопка с именем выбранного проекта; клик → поле поиска + отсортированный по алфавиту список; ввод фильтрует; выбор → данные грузятся (как раньше); placeholder когда не выбран. Dashboard: работает только в режиме «single», тумблер «Все проекты» не затронут.

- [ ] **Step 5: История**

Run: `cd /home/claude-user/validator-contenthunter && git log --oneline <base>..HEAD`
Expected: ~9 коммитов (util, компонент, 7 страниц), дерево чистое.

---

## Self-Review (выполнено автором)

- **Покрытие спеки (§6 поиск+сортировка):** компонент+util (Tasks 1-2), 7 страниц (Task 3), сортировка `localeCompare('ru',numeric)` в util. ✓
- **Без мультивыбора/бэкенда:** компонент single-only; `X-Project-Id` (одиночный) не меняется; `projectHeaders()`/эндпоинты не тронуты. Мультивыбор — Фаза 2b (расширит компонент + 4 страницы + backend). ✓
- **Brand остаётся одиночным:** распаковка — форма редактирования одного проекта; в 2a она получает поиск+сортировку, но мультивыбор там НЕ планируется и в 2b (разведка подтвердила: multi бессмыслен для edit-формы). schemes/contract — тоже single (исключены спекой). ✓
- **`@update:model-value` vs `@change`:** кастомный компонент не эмитит DOM `change`; используем `update:model-value`, который отрабатывает после v-model-сеттера `selectedProjectId`. ✓
- **Плейсхолдеры:** util и компонент приведены целиком; свапы — канонический паттерн + точный per-page источник опций (`projects` vs `allProjects`) и расположение. Исполнитель читает точную разметку каждой страницы (она единообразна). ✓
- **Alias `@`:** проверен — `tsconfig.json paths {"@/*":["./src/*"]}` + `vite.config.ts alias`, страницы уже импортят через `@/...`. ✓
- **Плейсхолдер-сброс (отвод codex P2):** нативные селекты используют `<option :value="0" disabled>`/`value="" disabled` — плейсхолдер НЕ выбираемый, сброса в `0` через селект не было. Компонент сохраняет паритет: показывает placeholder как метку триггера при пустом `modelValue` (стартовое состояние) и не предлагает строку сброса. Регрессии нет. ✓
