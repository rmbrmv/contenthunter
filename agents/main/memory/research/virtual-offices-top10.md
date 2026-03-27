# Топ-10 виртуальных офисов для AI-агентов
> Ресёрч: визуальные UI/UX примеры дашбордов и рабочих пространств для AI-агентов  
> Дата: 2026-03-01

---

### 1. AutoGen Studio (Microsoft)
- **URL:** https://github.com/microsoft/autogen/tree/main/python/packages/autogen-studio
- **Demo:** https://autogenstudio.azurewebsites.net
- **Скриншот:** https://media.githubusercontent.com/media/microsoft/autogen/refs/heads/main/python/packages/autogen-studio/docs/ags_screen.png
- **Фишки:**
  - Полноценный GUI для создания и управления мульти-агентными командами
  - Sidebar с "галереей" агентов — можно выбирать и переконфигурировать
  - Playground-чат прямо в интерфейсе — задаёшь задачу, наблюдаешь как агенты думают
  - Визуализация "цепочки рассуждений" агента в реальном времени
  - Вкладки: Sessions / Build / Gallery — чёткое разделение рабочих пространств
  - Тёмная тема, минималистичный Material-стиль

---

### 2. Dify
- **URL:** https://github.com/langgenius/dify
- **Demo:** https://cloud.dify.ai
- **Скриншот:** https://raw.githubusercontent.com/langgenius/dify/main/images/GitHub_README_if.png
- **Фишки:**
  - Визуальный конструктор workflow с drag-and-drop нодами (как Figma, только для AI)
  - Панель "Orchestration" — видно всю цепочку агентов на канвасе
  - Встроенный RAG-пайплайн с визуализацией Knowledge Base
  - Аналитика в реальном времени: токены, стоимость, latency прямо в дашборде
  - Режим Chatflow vs Workflow — два типа рабочих пространств
  - Маркетплейс готовых темплейтов прямо в UI
  - Чистый современный дизайн с фиолетовым акцентом

---

### 3. Langflow
- **URL:** https://github.com/langflow-ai/langflow
- **Demo:** https://astra.datastax.com/langflow
- **Скриншот:** https://raw.githubusercontent.com/langflow-ai/langflow/dev/docs/static/img/langflow_basic_howto.gif
- **Фишки:**
  - Node-based визуальный редактор — каждый агент/инструмент это нода на канвасе
  - Цветовая кодировка нод по типу (LLM, Tool, Memory, Output — разные цвета)
  - Встроенный Playground справа от канваса — тестируешь не выходя из редактора
  - Панель компонентов слева с поиском — библиотека готовых блоков
  - Step-by-step debugging — можно пошагово выполнять граф
  - Экспорт в JSON / деплой как API одной кнопкой

---

### 4. Flowise
- **URL:** https://github.com/FlowiseAI/Flowise
- **Demo:** https://flowise-qn89.onrender.com
- **Скриншот:** https://github.com/FlowiseAI/Flowise/raw/main/images/flowise.gif
- **Фишки:**
  - Drag-and-drop canvas в стиле n8n, но специально под LLM-цепочки
  - Каждая нода раскрывается для настройки прямо на канвасе (inline config)
  - Встроенный чат-виджет для тестирования — появляется поверх редактора
  - Маркетплейс шаблонов (Marketplace) с preview перед установкой
  - Агент-ноды отличаются иконкой мозга, инструменты — гаечным ключом
  - Светлая и тёмная темы, адаптивный интерфейс

---

### 5. Rivet (Ironclad)
- **URL:** https://github.com/Ironclad/rivet
- **Demo:** https://rivet.ironcladapp.com
- **Скриншот:** https://rivet.ironcladapp.com/img/rivet-screenshot.png
- **Фишки:**
  - Десктопное приложение (Electron) — ощущение как у профессионального инструмента
  - Граф-редактор с "подграфами" — можно вкладывать агентов друг в друга
  - Realtime выполнение: видно как данные "текут" через ноды (анимация рёбер)
  - Встроенный отладчик с breakpoints на нодах
  - Split-view: граф слева, результаты/логи справа
  - Поддержка "записи" промптов — история версий прямо в UI
  - Профессиональный dark UI в стиле DAW (цифровой аудиостанции)

---

### 6. n8n (AI Agent Mode)
- **URL:** https://github.com/n8n-io/n8n
- **Demo:** https://n8n.io
- **Скриншот:** https://raw.githubusercontent.com/n8n-io/n8n/master/assets/n8n-screenshot-readme.png
- **Фишки:**
  - Канвас в духе Miro — бесконечное рабочее поле, зум, мини-карта
  - AI Agent нода выглядит иначе чем обычные — специальный "мозговой" значок
  - "Sticky notes" прямо на канвасе — документация рядом с логикой
  - Исполнение подсвечивает пройденный путь зелёным — сразу видно что отработало
  - Панель выполнений (Executions) с историей и diff между запусками
  - 400+ интеграций в боковой библиотеке с живым поиском

---

### 7. AgentGPT (Reworkd)
- **URL:** https://github.com/reworkd/AgentGPT
- **Demo:** https://agentgpt.reworkd.ai
- **Скриншот:** https://raw.githubusercontent.com/reworkd/AgentGPT/main/next/public/banner.png
- **Фишки:**
  - Простейший вход в мир агентов — одно поле "имя агента" + "цель"
  - Визуализация "дерева задач" — агент сам разбивает цель на подзадачи и ты видишь дерево
  - Каждая задача имеет статус (thinking / executing / complete) с анимацией
  - Timeline выполнения в центре экрана — как лента событий
  - Минималистичный фиолетово-чёрный дизайн в стиле "cyberpunk SaaS"
  - Добавление инструментов (поиск, код) переключателями-тоглами

---

### 8. SuperAGI
- **URL:** https://github.com/TransformerOptimus/SuperAGI
- **Demo:** https://app.superagi.com
- **Скриншот:** https://superagi.com/wp-content/uploads/2023/05/SuperAGI_dashboard.png
- **Фишки:**
  - "Agentic workspace" с боковой панелью агентов как в Slack (список чатов)
  - Каждый агент — отдельная "карточка" с avatar, статусом и прогрессом
  - Concurrent agents — несколько агентов работают одновременно, и это видно
  - Вкладка Toolkits — маркетплейс инструментов с иконками и описаниями
  - Граф памяти агента — визуализация векторных воспоминаний
  - Dashboard с метриками: токены, задачи, время работы

---

### 9. OpenHands (All-Hands AI)
- **URL:** https://github.com/All-Hands-AI/OpenHands
- **Demo:** https://app.all-hands.dev
- **Скриншот:** https://raw.githubusercontent.com/OpenHands/docs/main/openhands/static/img/openhands-ui-screenshot.png
- **Фишки:**
  - Split-панель: чат с агентом слева, "рабочий стол агента" справа
  - Правая панель показывает терминал/браузер/редактор — что агент делает прямо сейчас
  - Визуальный браузер агента — видишь что он "видит" на экране
  - File explorer в интерфейсе — агент работает с файлами, и ты это видишь
  - Step history — лента "шагов" агента с иконками (code / browse / terminal)
  - Деловой минималистичный дизайн, похожий на IDE

---

### 10. FastGPT
- **URL:** https://github.com/labring/FastGPT
- **Demo:** https://fastgpt.io
- **Скриншот:** https://raw.githubusercontent.com/labring/FastGPT/main/.github/imgs/intro1.png
- **Дополнительные скриншоты:**
  - https://raw.githubusercontent.com/labring/FastGPT/main/.github/imgs/intro2.jpg
  - https://raw.githubusercontent.com/labring/FastGPT/main/.github/imgs/intro3.png
- **Фишки:**
  - Визуальный "оркестратор" с нодами — специализирован под RAG + Agent комбинации
  - Debug Mode прямо в редакторе — можно прокликать каждую ноду и увидеть I/O
  - Knowledge Base панель: загружаешь документы и видишь как они разбиваются на chunks
  - Встроенная аналитика разговоров с возможностью аннотировать ответы
  - Особая нода "UserInput" — можно создавать интерактивные формы внутри агента
  - Чистый современный дизайн с синей акцентной палитрой, китайский дизайн-стандарт (очень аккуратный)

---

## Сводная таблица фишек

| Продукт | Canvas/граф | Real-time | Debug | Мульти-агент | Маркетплейс |
|---------|-------------|-----------|-------|--------------|-------------|
| AutoGen Studio | ❌ (chat-based) | ✅ | ✅ | ✅ | ❌ |
| Dify | ✅ | ✅ | ✅ | ✅ | ✅ |
| Langflow | ✅ | ✅ | ✅ | ✅ | ❌ |
| Flowise | ✅ | ✅ | ❌ | ✅ | ✅ |
| Rivet | ✅ | ✅ | ✅ | ✅ | ❌ |
| n8n | ✅ | ✅ | ✅ | ✅ | ✅ |
| AgentGPT | ❌ (task tree) | ✅ | ❌ | ❌ | ❌ |
| SuperAGI | ❌ (sidebar) | ✅ | ❌ | ✅ | ✅ |
| OpenHands | ❌ (split-view) | ✅ | ✅ | ❌ | ❌ |
| FastGPT | ✅ | ✅ | ✅ | ✅ | ❌ |

## Выводы для дизайна виртуального офиса

**Паттерны, которые повторяются у лидеров:**
1. **Canvas + Sidebar** — граф в центре, библиотека компонентов слева
2. **Real-time execution feedback** — подсветка активных нод/путей
3. **Встроенный Playground** — тестируй не выходя из редактора
4. **Цветовая кодировка** — типы нод различаются цветом/иконкой
5. **История выполнений** — timeline всего что делал агент
6. **Split-view** — код/граф + результат рядом

**Что ещё не сделал никто:**
- Настоящая "комнатная" метафора офиса (как Gather.town, но для агентов)
- Аватары агентов с "присутствием" (онлайн/оффлайн/занят)
- Collaboration: несколько людей редактируют одновременно (как в Figma)
- "Новости дня" — что агенты сделали за ночь в виде digest-ленты
