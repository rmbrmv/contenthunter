# TT post-switch verify — приоритет `@handle` при чтении профиля (дизайн)

**Дата:** 2026-05-14
**Баг:** `tt_post_switch_verify_unrecoverable` — OpenProject WP [#67](https://openproject.contenthunter.ru/work_packages/67)
**Триаж:** `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`
**Ветка:** `worktree-tt-publish-triage-2026-05-14`

## Проблема

После выбора аккаунта в TikTok-свитчере оркестратор проверяет, что открыт нужный
профиль, через `_post_switch_verify_handle` → `get_current_account_from_profile`
(`account_switcher.py`). Функция собирает все токены в полосе `y_top ≤ header_y_max`
(для TikTok `header_y_max = 700`), которые проходят эвристику `_looks_like_username`,
сортирует кандидатов по `y_top` и возвращает **самый верхний**.

На экране профиля TikTok отображаемое имя профиля рендерится **выше** `@handle`,
а `_looks_like_username` слишком широкая — принимает за username:

- слова из display name (`Girl`, `Unpacking`, `Relisme`, `Unpack`);
- любой токен с цифрой, включая голые числа-badge'и из топ-бара (`11` на `y≈164`).

Реальный `@handle` стабильно сидит на `y≈574` — ниже имени профиля и ниже badge'ей.
Итог: verify возвращает мусорный верхний токен → `mismatch` (или `unknown` при
`header_y_max=260`) → успешный свитч трактуется как несостоявшийся → renav + полный
retry → `tt_post_switch_verify_unrecoverable`. **16 падений TikTok-выкладки за
2026-05-14** (16 устройств, raspberry 1/2/7/9/10, весь день 04:50–13:41).

Подтверждено репликацией `get_current_account_from_profile` на реальных
`tt_4_target_profile_renav` дампах:

| task | target | `@handle` (y) | имя профиля выше (y) | verify(700) вернул |
|---|---|---|---|---|
| 5817 | `relism_e` | `@relism_e` (574) | «Unpacking Girl» (503) | `girl` ❌ |
| 5593 | `mariaforsale` | `@mariaforsale` (574) | badge `11` (164) | `11` ❌ |
| 5799 | `relis_unpack` | `@relis_unpack` (574) | «Relisme Unpack» (503) | `relisme` ❌ |

Во всех трёх верный `@handle` присутствует в дампе и в полосе — но возвращается не он.

## Рассмотренные варианты

1. **Приоритет `@`-токена в `get_current_account_from_profile`** — настоящий TT-хэндл
   на экране профиля идёт с префиксом `@`; при наличии `@`-токена в полосе брать его,
   bare-токен — fallback. ✅ **Выбран.**
2. **Ужесточить `_looks_like_username`** — отсекать голые числа и слова из display name.
   Отклонён: функция шарится 5+ вызовами IG/TT/YT, плотно покрыта тестами — высокий
   blast radius.
3. **Сузить `header_y_max` для TikTok** — не применимо: `@handle` на `y≈574` уже внутри
   полосы `700`, проблема не в полосе, а в выборе токена.

## Решение

Одно изменение в `account_switcher.py` — функция `get_current_account_from_profile`.

Сейчас:

```python
candidates = []
for el in elements:
    y_top = el.bounds[1]
    if y_top > header_y_max:
        continue
    for raw in (el.text, el.content_desc):
        if not raw:
            continue
        for tok in re.split(r'\s+|\n', raw):
            if _looks_like_username(tok):
                candidates.append((y_top, AccountSwitcher._normalize_username(tok)))
if not candidates:
    return None
candidates.sort()           # сверху вниз
return candidates[0][1]
```

Станет — ключ сортировки получает ведущий разряд `is_bare`:

```python
is_bare = 0 if tok.lstrip().startswith('@') else 1
candidates.append((is_bare, y_top, AccountSwitcher._normalize_username(tok)))
...
candidates.sort()           # @-токены вперёд, внутри группы — сверху вниз
return candidates[0][2]
```

Поведение:

- **Есть `@`-токен в полосе** → берётся он (среди нескольких `@`-токенов — верхний по
  `y_top`). Это настоящий TT-хэндл.
- **`@`-токенов нет** → все кандидаты `is_bare=1`, сортировка вырождается в прежнюю
  `(y_top, norm)` → возвращается верхний bare-токен, как сейчас.

Docstring функции обновляется: добавляется строка про приоритет `@`-префикса.
`_looks_like_username`, `header_y_max`, `_post_switch_verify_handle` и вызывающая
логика свитчера — **не трогаются**.

## Почему это безопасно для IG / YT

`get_current_account_from_profile` вызывается из 6 мест (IG/TT/YT switching +
`publisher_base.py`). У IG и YT в header'е экрана профиля `@`-префикса обычно нет →
все кандидаты получают `is_bare=1` → ключ сортировки эквивалентен прежнему
`(y_top, norm)` → результат идентичен текущему. Изменение строго аддитивно: оно
может только *поднять* `@`-токен в приоритете, а при отсутствии `@`-токенов — no-op.

Существующие тесты функции (`tests/test_account_switcher.py`) остаются зелёными:

- `test_get_current_from_ig_profile` → `acme_brand` (bare → fallback-ветка);
- `test_tt_profile_screen_username_detected_with_widened_range` → `jalaladinova`
  (если фикстура содержит `@jalaladinova` — `@`-ветка, тот же результат; если bare —
  fallback, тот же результат);
- `test_get_current_from_profile_with_cyrillic_username` → `инакент-т2щ` (bare → fallback);
- `test_get_current_returns_none_*` / `test_get_current_ignores_elements_below_header`
  → `None` (логика полосы и пустого списка не меняется).

## Тестирование (TDD — тесты вперёд)

1. **Новые юнит-тесты `get_current_account_from_profile`** с фикстурами из реальных
   упавших дампов (кладём в `tests/fixtures/`):
   - `tt5817_tt4_renav.xml` → `get_current_account_from_profile(els, header_y_max=700)`
     == `relism_e` (display name «Unpacking Girl» выше — не должна победить);
   - `tt5593_tt4_renav.xml` → `== mariaforsale` (badge `11` выше — не должен победить);
   - `tt5799_tt4_renav.xml` → `== relis_unpack` (display name «Relisme Unpack» выше).
2. **Тест IG-инвариантности** — синтетический дамп с двумя bare-токенами (без `@`):
   возвращается верхний по `y_top`, как до правки.
3. **Тест приоритета** — синтетический дамп: bare-токен на `y=100` + `@`-токен на
   `y=300` в одной полосе → возвращается `@`-токен (приоритет важнее y_top).
4. **Регресс** — полный прогон `tests/test_account_switcher.py`,
   `tests/test_post_switch_renav.py`, `tests/test_switcher_read_only.py`,
   `tests/test_yt_post_switch_verify.py` — 0 регрессий. Шире — весь `pytest`,
   сверка с pre-existing fails на `origin/main` (2 известных: `test_publish_guard`
   tiktok-column-null, `test_switcher_read_only` yt_happy_path — не наши).

## План выката (полный цикл)

1. TDD-реализация в `worktree-tt-publish-triage-2026-05-14` (тесты → код → зелёный сьют).
2. `codex review` диффа раундами до 0 P1/P2.
3. PR в `GenGo2/delivery-contenthunter`, squash-merge в `main`.
4. Деплой на prod-чекаут `/root/.openclaw/workspace-genri/autowarm`: fast-forward +
   PM2 `autowarm` restart, проверка `exec cwd` (защита от path-drift).
5. Live smoke: ре-выкладка одной из 16 задач через `publish_queue` (UPDATE → pending,
   `publish_task_id=NULL`), проверка, что post-switch verify прошёл и публикация
   двинулась дальше свитчера.
6. Обновить WP #67 (статус + house-style комментарий) и
   `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`.

## Не входит в scope

- Ужесточение `_looks_like_username` (вариант 2) — отдельная задача при необходимости.
- `tt_upload_confirmation_timeout`, `tt_profile_tab_broken`, retry-suffix gap мэппера —
  runner-up'ы из триажа, отдельными тикетами.
- Изменение `header_y_max` / device-config.
