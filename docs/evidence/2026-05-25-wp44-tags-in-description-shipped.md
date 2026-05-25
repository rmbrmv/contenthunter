# WP #44 — Добивка тегов в описание публикаций — SHIPPED 2026-05-25

**Задача:** OpenProject #44 «Выкладка (добавить теги в описание)».
**Артефакты:** spec `docs/superpowers/specs/2026-05-25-wp44-publish-tags-design.md`, plan `docs/superpowers/plans/2026-05-25-wp44-publish-tags.md`.

## Что было не так
Клиенты задают теги в планировщике (поле `hashtags`, ≤5). Не было механизма «добивки»: если тегов меньше 5, набор оставался коротким, и одни и те же теги повторялись изо дня в день (IG/TT это не любят). Пункт 3 задачи (литерал «Теги:» в описании клиента «Еноты») — по решению Данила это ручная ошибка клиента, код не трогали.

## Что сделано
Новый модуль `hashtag_enrich.js` в autowarm:
- `enrichHashtags(clientTags, brandKeywords, opts)` — клиентские теги + случайная добивка из `keywords` бренд-профиля (распаковки) до 5, когда у контента <5 тегов. Нормализация keyword→тег: lowercase, склейка без пробелов, без пунктуации, дроп >30 символов, дедуп (симметричный).
- `getBrandKeywords(pool, projectId)` — чтение `validator_brand_profiles.keywords`, `[]` на любой проблеме.

Врезка в `server.js` в обе точки сборки caption (`assignUnicResultsToQueue` + ручной endpoint). Едино для IG/TT (теги в caption) и YouTube (теги в поле описания через публикатор). Рандомизация — на каждую публикацию (per строка очереди).

Под kill-switch: `PUBLISH_TAG_FILL_ENABLED` (default on), `PUBLISH_TAG_FILL_TARGET=5`, `PUBLISH_TAG_FILL_MAXLEN=30` (защита от NaN).

## Реализация и проверка
- Репозиторий `GenGo2/delivery-contenthunter`, ветка `feat/wp44-publish-tags-20260525`, merge → `main` (`ae86367`).
- 16 unit-тестов (`node --test hashtag_enrich.test.js`) — зелёные.
- 2 spec-review + 3 code-quality review субагентами + финальное холистическое ревью (Ready to merge).
- Live-smoke на реальных данных проекта 107 (Еноты): 16 keywords → добивка к 2 клиентским тегам даёт 5 чистых склеенных тегов, повторный вызов даёт другой рандомный набор; 5 тегов — без изменений; дубль не задваивается.
- Деплой: прод-checkout `/root/.openclaw/workspace-genri/autowarm` (auto-push hook), PM2 `autowarm` (id=35) рестарт — online, `assign-queue` цикл без ошибок.

## Что осталось (backlog)
- Live-верификация на новых реальных публикациях (статус OpenProject → Тестирование).
- Минорные (не блокеры, см. BACKLOG): ручная постановка с явным caption для IG/TT не пишет теги в `publish_queue.hashtags` (пре-existing, теги уже в строке caption); нет лог-предупреждения при склейке многословного keyword; `getBrandKeywords` вызывается N раз на проект в батче (мемоизация — опционально).
