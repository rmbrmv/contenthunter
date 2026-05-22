# Design — WP #105 (Round 2): доверять dumpsys при залипшем uiautomator

**WP:** https://openproject.contenthunter.ru/wp/105
**Категория:** `ig_app_launch_failed`
**Статус:** рецидив после частичного фикса PR #76 (`f480219`). WP вернулась в «В разработке».
**Предыдущий спек:** [2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md](2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md)

## 1. Что произошло после PR #76

PR #76 ввёл cross-source check в `_foreground_pkg` (Layer 1) + settle-wait (Layer 2). Codex review round 2 добавил **confirming-poll**: когда `dumpsys=target`, а `uiautomator∈{launcher,пусто}`, прежде чем доверять dumpsys, код 3 раза по 0.8с перечитывает uiautomator и доверяет target **только если uiautomator догонит**. Цель — не принять за успех ситуацию, когда поверх target реально висит overlay.

В проде uiautomator **не догоняет** dumpsys в пределах этого окна (минуты, а не 1 секунда). Confirming-poll никогда не подтверждает → `_foreground_pkg` возвращает launcher → fail. Защита от ложного успеха превратилась в генератор ложного провала.

### Свежие данные (2026-05-22)

`ig_app_launch_failed` за последние 5 дней (prod, по `error_code`):

| Дата | Фейлов |
|---|---|
| 2026-05-18 | 0 |
| 2026-05-19 | 4 |
| 2026-05-20 | 3 |
| 2026-05-21 | 1 |
| **2026-05-22** | **6–7** ← пик |

22.05 — топ-1 кодовый IG-фейл. Raspberries 1/2/3/5, разные устройства и аккаунты → код-баг, не железо.

### Точная трассировка (task 9227, gengo_sales, Pi #3, 2026-05-22 07:48)

```
07:48:14  ig_foreground_recovery: focus=...launcher attempt=1     ← _ensure_app_foregrounded
07:48:18  ig_app_foregrounded_after_recovery: attempt=2           ← dumpsys видит IG, ОК
07:48:36  foreground_pkg_disagree: dumpsys=instagram uiautomator=launcher
07:49:32  foreground_pkg_disagree: dumpsys=instagram uiautomator=launcher
07:50:29  foreground_pkg_disagree: dumpsys=instagram uiautomator=launcher
07:51:28  foreground_pkg_disagree: dumpsys=instagram uiautomator=launcher
07:52:20  foreground_pkg_disagree: dumpsys=instagram uiautomator=launcher
07:53:11  ui_dump step=ig_1_feed ... package="com.sec.android.app.launcher"
07:53:17  не удалось запустить приложение step=ig_1_feed текущий='launcher'
07:53:29  fail: Instagram не запустился
```

5 disagree-событий за ~4.5 минуты, `dumpsys=instagram` стабильно во всех. `switcher_settle_wait_recovered` — 0 раз.

## 2. Root cause (уточнённый)

- **dumpsys корректен** — подтверждён дважды независимо: `_ensure_app_foregrounded` (07:48:18) и все 5 disagree-событий показывают `topResumedActivity=com.instagram.android`.
- **скриншот корректен** — финальный screenshot показывает IG на экране (evidence WP + предыдущий раунд).
- **uiautomator XML-дамп персистентно залипает** на launcher-окне. `dump_ui` запускает `uiautomator dump`, который снимает иерархию окон из AccessibilityService; при незавершённом window-transition launcher-окно остаётся в снимке и отдаётся вместо IG, отставая на минуты.

Сломан **именно uiautomator**, а не реальное состояние приложения. Два независимых источника (dumpsys + скриншот) согласны, что IG поднят. Чистого механизма «перезапустить» uiautomator через shell нет, поэтому фикс — доверять надёжному источнику (dumpsys), когда uiautomator залип.

## 3. Design — доверять dumpsys + проверка стабильности

Единственная точка изменения — функция `_foreground_pkg(target_pkg)` внутри `_open_app` (`account_switcher.py` ~5156–5208). Функция общая для IG/TT/YT; сигнатура «dumpsys=target, ui∈{launcher,пусто}» платформонезависима, поэтому фикс покрывает все три платформы.

### Новая логика разрешения разногласия

Ветка `pkg_dump == target_pkg and pkg_ui in ('', 'com.sec.android.app.launcher')` заменяется на:

1. **Быстрый catch-up uiautomator** (сохраняем существующий путь, чуть короче — 3 повтора по ~0.7с). Если uiautomator догнал и видит target → `return target`. Покрывает исходный «1-секундный race», где источники быстро сходятся, и даёт лучший из возможных исходов (оба согласны).

2. **Если не догнал → проверка стабильности dumpsys.** Перечитать `topResumedActivity` 3 раза с интервалом ~0.5с (дёшево, без uiautomator). Если **все 3 чтения == target** → доверяем dumpsys, `return target` + эмит маркер-события `switcher_foreground_trusted_dumpsys`.

3. **Если dumpsys нестабилен** (хоть одно чтение ≠ target) → `return pkg_ui or pkg_dump` (текущее поведение — честный launcher; приложение реально не на переднем плане).

Псевдокод вставляемой ветки:

```python
if pkg_dump == target_pkg and pkg_ui in ('', 'com.sec.android.app.launcher'):
    # (1) короткий catch-up uiautomator — лучший исход, оба согласны
    for _ in range(3):
        time.sleep(0.7)
        xml2 = self.p.dump_ui(retries=1) or ''
        m_ui2 = re.search(r'package="([^"]+)"', xml2)
        if (m_ui2.group(1) if m_ui2 else '') == target_pkg:
            return target_pkg
    # (2) uiautomator залип — доверяем dumpsys, если он СТАБИЛЕН
    if _TRUST_DUMPSYS_ON_STALE_UI:
        stable = True
        for _ in range(3):
            time.sleep(0.5)
            top_n = self.p.adb("dumpsys activity activities | "
                               "grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
            m_n = re.search(r'\s([\w\.]+)/[\w\.]+', top_n)
            if (m_n.group(1) if m_n else '') != target_pkg:
                stable = False
                break
        if stable:
            self.p.log_event('info',
                f'foreground_trusted_dumpsys: dumpsys={pkg_dump} '
                f'uiautomator={pkg_ui} (stale UI, dumpsys stable)',
                meta={'category': 'switcher_foreground_trusted_dumpsys',
                      'pkg_dumpsys': pkg_dump, 'pkg_uiautomator': pkg_ui,
                      'target_pkg': target_pkg, 'step': step_name,
                      'stable_reads': 3})
            return target_pkg
    # (3) dumpsys нестабилен или kill-switch off — честный launcher
    return pkg_ui or pkg_dump
```

### Сохранённые защиты (НЕ трогаем)

- **Реальный overlay** (`pkg_ui` НЕ launcher/пусто — permissioncontroller / sbrowser / IME): возвращаем `pkg_ui`, dumpsys НЕ доверяем, чтобы отработал `_dismiss_blocking_overlays`. Это защита Codex P2 round 1 — остаётся нетронутой, потому что новый путь активируется только при `pkg_ui ∈ {launcher, пусто}`.
- `pkg_ui == target_pkg` → возвращаем target (UI ground-truth подтверждает).
- disagree-событие `switcher_foreground_pkg_disagree` логируется как сейчас.

### Kill-switch

`_TRUST_DUMPSYS_ON_STALE_UI = os.getenv('SWITCHER_TRUST_DUMPSYS_ON_STALE_UI', '1') != '0'`

Default — включён. При `SWITCHER_TRUST_DUMPSYS_ON_STALE_UI=0` поведение откатывается к текущему (возврат launcher после неудачного catch-up). Мгновенный откат без передеплоя.

## 4. Наблюдаемость

Новое событие `switcher_foreground_trusted_dumpsys` с meta {pkg_dumpsys, pkg_uiautomator, target_pkg, step, stable_reads}. После деплоя:
- считаем частоту нового пути за 24ч;
- кросс-сверяем task'и с этим событием против финального статуса — если они доходят до published/успешных downstream-шагов, это фактическое доказательство, что доверие dumpsys безопасно;
- если task с trusted_dumpsys всё равно падает дальше — сигнатура падения подскажет, действительно ли IG был на экране.

## 5. Что НЕ трогаем (сужение скоупа)

- `_ensure_app_foregrounded` — корректен (dumpsys там не врёт). Гипотеза прошлого раунда «recovery врёт» опровергнута: dumpsys стабильно прав.
- L2 settle-wait (5261–5283) — оставляем как safety net. Он почти перестанет срабатывать, т.к. первый же `_foreground_pkg` теперь вернёт target и `_open_app` выйдет с early-return.
- `am start` retry-логика, `dump_ui`, `OPEN_APP_WAIT_S` — без изменений.

## 6. Тесты (`test_account_switcher.py`, fake-proxy)

| Сценарий | Ожидание |
|---|---|
| dumpsys=IG стабильно + uiautomator=launcher всегда | `_open_app`=True, эмит `switcher_foreground_trusted_dumpsys` (главный кейс рецидива) |
| uiautomator догоняет на 2-й итерации catch-up | True, БЕЗ trusted_dumpsys (быстрый race) |
| dumpsys плавает (IG→launcher→IG) | False — не доверяем нестабильному |
| pkg_ui = реальный overlay (permissioncontroller) | возвращает overlay, dumpsys НЕ доверяет (регресс-защита Codex P2) |
| kill-switch=0 + dumpsys=IG + uiautomator=launcher | False (старое поведение) |
| both=target | True, без disagree-события |

Перед написанием тестов сверить имена методов fake-proxy с реальным `DevicePublisher` (`adb`, `dump_ui`, `log_event`, `set_step`) — анти-дрейф (урок PR #52).

## 7. Деплой

- Python-публикатор спавнится свежим на каждую задачу → **PM2 restart не нужен**.
- Раскатка: cherry-pick фикса в prod autowarm (`/root/.openclaw/workspace-genri/autowarm/`).
- Перед отдачей пользователю — `codex review` спека → плана → диффа, раундами до 0 P1/P2 (стандартная практика).
- Проверка на проде: за 24ч после деплоя query `switcher_foreground_trusted_dumpsys` + динамика `ig_app_launch_failed` (цель — к нулю).

## 8. Риски

| Риск | Митигация |
|---|---|
| dumpsys врёт (IG крашнулся, но `topResumedActivity` устарел) → доверяем зря | Теоретический: при краше ActivityManager обновляет topResumedActivity на launcher. Стабильность-чек (3×) отсекает мгновенные блипы; downstream-шаги переключения работают по реальному UI и упадут с честной причиной, если IG реально нет. |
| Новый путь маскирует реальные «не запустился» | Срабатывает только при `pkg_ui∈{launcher,пусто}` И стабильном dumpsys=target. Реальный overlay (`pkg_ui`=overlay) идёт прежним путём. |
| Параллельные сессии редактируют `_foreground_pkg` | Worktree + atomic commit + зелёный pytest перед merge (per parallel-sessions practice). |

## 9. Связанные сущности

- PR #76 (`f480219`) — Round 1 этого же WP; данный спек его дорабатывает.
- WP #74 Round 2 — YT foreign-foreground guard (концептуально близкий guard pattern).
- WP #73 — `ig_share_tap_no_progress` — другой IG-баг, не дублируется.
