# WP#134 — yt_6 soft-pass при камере YouTube Shorts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перестать фатально ронять шаг `yt_6` с маскарадом `yt_create_menu_not_reached`, когда после тапа «+» телефон оказывается в камере YouTube Shorts (или ином create-экране YouTube), чтобы отработал устойчивый путь загрузки `Shell_UploadActivity`.

**Architecture:** Точечная вставка в `account_switcher.py::_tap_plus_and_verify` (ветка `strict_verify and not hits`) перед финальным fail: если foreground-пакет всё ещё YouTube — `_ok` (soft-pass) + телеметрия + kill-switch. Drift (foreground ≠ YouTube) по-прежнему падает. Два новых module-level хелпера (kill-switch + детектор-маркер для телеметрии). Только YT-ветка (`strict_verify=True`); IG/TT не затронуты.

**Tech Stack:** Python 3, pytest, `unittest.mock.MagicMock`. Репозиторий `GenGo2/delivery-contenthunter`. Dev-чекаут: `/home/claude-user/autowarm-testbench`. Prod: `/root/.openclaw/workspace-genri/autowarm` (auto-push git-hook, PM2).

**Спека:** `docs/superpowers/specs/2026-05-26-wp134-yt-shorts-camera-design.md`

---

## Контекст для исполнителя (прочитать до старта)

- Реальный механизм загрузки YT в `publisher_youtube.py::publish_youtube_short` — прямой интент **`Shell_UploadActivity`** (минует камеру и галерею). Перед ним `_normalize_yt_state_pre_upload` делает `force-stop` YouTube и уходит на home-feed, поэтому меню создания, открытое на `yt_6`, всё равно закрывается. Значит строгая проверка create-menu на `yt_6` для загрузки не нужна — она лишь рудиментарный гейт.
- Падение происходит в `_ensure_correct_account()` (свич) **до** пути загрузки, поэтому soft-pass на `yt_6` разблокирует загрузку.
- **Layer C** в `_tap_plus_and_verify` (строки ~4992–5021, под `strict_verify and _guard_enabled()`) уже проверяет foreground после тапа: при `fg != yt_pkg` пытается recovery/фейлит `..._app_not_foregrounded`. При `fg == yt_pkg` Layer C **инертен** — управление доходит до нашей новой ветки. Наш soft-pass имеет **отдельный** kill-switch (не `_guard_enabled`).
- `editor_triggers` YT = `['Добавить описание','Add description','Опубликовать','Upload','Видео','Прямой эфир','Live']`. В проде камера дала пустой/разреженный dump (вкладки «Видео/Shorts/Эфир/Запись» рисуются на GL-поверхности и не попадают в XML), поэтому exact-match вернул `[]`. Фикстура камеры (Task 2) это воспроизводит: **не** содержит токенов `editor_triggers`.

## Структура файлов

- Modify: `account_switcher.py` — 2 module-level хелпера (рядом с `_premium_dismiss_enabled`, ~стр. 226) + 1 вставка в `_tap_plus_and_verify` (ветка `strict_verify and not hits`, ~стр. 5040).
- Create: `tests/fixtures/yt_create_menu/shorts_camera.xml` — разреженный dump камеры Shorts.
- Modify: `tests/test_yt_create_menu_strict_verify.py` — новые тесты (тот же модуль, переиспользуем `_stub_switcher_with_dump`).

Все шаги выполняются в dev-чекауте `/home/claude-user/autowarm-testbench`. Тесты: `cd /home/claude-user/autowarm-testbench && python -m pytest <path> -v`.

---

## Task 0: Подготовка ветки

**Files:** —

- [ ] **Step 1: Синхронизировать testbench и создать ветку**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin main
git stash -u 2>/dev/null || true   # на случай локальных правок параллельных сессий
git checkout -b feat/wp134-yt-shorts-camera-soft-pass origin/main
git log --oneline -1
```
Expected: HEAD на свежем `origin/main`.

- [ ] **Step 2: Прогнать релевантные тесты ДО изменений (зелёная база)**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_premium_promo_dismiss.py tests/test_yt_create_menu_fg_guard.py -q`
Expected: всё PASS (фиксируем, что база зелёная до правок).

---

## Task 1: Kill-switch + детектор-маркер (module-level хелперы)

**Files:**
- Modify: `account_switcher.py` (после `_premium_dismiss_enabled`, ~стр. 226)
- Test: `tests/test_yt_create_menu_strict_verify.py`

- [ ] **Step 1: Написать падающие тесты для хелперов**

Добавить в конец `tests/test_yt_create_menu_strict_verify.py`:

```python
# ─── WP #134: soft-pass при камере YouTube Shorts ──────────────────────────
import os as _os


def test_yt6_accept_nonmenu_foreground_default_on(monkeypatch):
    monkeypatch.delenv("YT6_ACCEPT_NONMENU_FOREGROUND", raising=False)
    assert _asw._yt6_accept_nonmenu_foreground_enabled() is True


def test_yt6_accept_nonmenu_foreground_kill_switch_off(monkeypatch):
    monkeypatch.setenv("YT6_ACCEPT_NONMENU_FOREGROUND", "0")
    assert _asw._yt6_accept_nonmenu_foreground_enabled() is False


def test_yt_is_shorts_camera_true_on_add_track_marker():
    xml = '<hierarchy><node content-desc="Добавить трек"/></hierarchy>'
    assert _asw._yt_is_shorts_camera(xml) is True


def test_yt_is_shorts_camera_true_on_english_marker():
    xml = '<hierarchy><node text="Add sound"/></hierarchy>'
    assert _asw._yt_is_shorts_camera(xml) is True


def test_yt_is_shorts_camera_false_on_create_menu():
    xml = '<hierarchy><node text="Опубликовать"/><node text="Добавить видео"/></hierarchy>'
    assert _asw._yt_is_shorts_camera(xml) is False


def test_yt_is_shorts_camera_false_on_empty_or_none():
    assert _asw._yt_is_shorts_camera("") is False
    assert _asw._yt_is_shorts_camera(None) is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_create_menu_strict_verify.py -k "yt6_accept or yt_is_shorts_camera" -v`
Expected: FAIL — `AttributeError: module 'account_switcher' has no attribute '_yt6_accept_nonmenu_foreground_enabled'`.

- [ ] **Step 3: Реализовать хелперы**

В `account_switcher.py`, сразу после функции `_premium_dismiss_enabled` (после строки `return os.environ.get('YT_PREMIUM_DISMISS_ENABLED', '1') != '0'`), добавить:

```python


# ─────────────────────────────────────────────────────────────────────────────
# WP #134 — yt_6: «+» открывает камеру YouTube Shorts напрямую (не bottom-sheet)
# ─────────────────────────────────────────────────────────────────────────────
def _yt6_accept_nonmenu_foreground_enabled() -> bool:
    """[WP #134] Kill-switch для soft-pass yt_6.

    Когда после тапа «+» мы остались ВНУТРИ YouTube (камера Shorts / иной
    create-экран) вместо bottom-sheet «меню создания», это не фатально:
    загрузка идёт через Shell_UploadActivity. Default ON. Установите
    `YT6_ACCEPT_NONMENU_FOREGROUND=0` чтобы откатиться к строгому fail.
    """
    return os.environ.get('YT6_ACCEPT_NONMENU_FOREGROUND', '1') != '0'


# Маркеры верхнего chrome камеры YouTube Shorts (Android-views, в отличие от
# GL-вкладок «Видео/Shorts/Эфир/Запись», которых часто нет в uiautomator-dump).
# Используются ТОЛЬКО для телеметрии (под-флаг), решение soft-pass принимается
# по foreground-пакету, а не по этим маркерам. Сверка case-insensitive.
_YT_SHORTS_CAMERA_MARKERS: tuple[str, ...] = (
    'добавить трек',
    'add sound',
    'add a sound',
)


def _yt_is_shorts_camera(xml: Optional[str]) -> bool:
    """[WP #134] Эвристика «экран — камера YouTube Shorts» для телеметрии.
    НЕ гейтит soft-pass. Pure-функция над строкой dump'а. Пустой/None → False.
    """
    if not xml:
        return False
    low = xml.lower()
    return any(m in low for m in _YT_SHORTS_CAMERA_MARKERS)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_create_menu_strict_verify.py -k "yt6_accept or yt_is_shorts_camera" -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_strict_verify.py
git commit -m "feat(wp134): kill-switch + shorts-camera marker helpers"
```

---

## Task 2: Фикстура разреженного dump'а камеры Shorts

**Files:**
- Create: `tests/fixtures/yt_create_menu/shorts_camera.xml`

- [ ] **Step 1: Создать фикстуру**

Создать `tests/fixtures/yt_create_menu/shorts_camera.xml` со следующим содержимым (разреженный dump: верхнее chrome камеры присутствует, вкладки/токены `editor_triggers` — НЕТ, чтобы exact-match дал `[]` как в проде):

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" package="com.google.android.youtube" class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node index="0" text="" content-desc="Закрыть" class="android.widget.Button" clickable="true" bounds="[24,120][120,216]"/>
    <node index="1" text="" content-desc="Добавить трек" class="android.widget.Button" clickable="true" bounds="[360,120][720,216]"/>
    <node index="2" text="15" content-desc="" class="android.widget.TextView" clickable="true" bounds="[960,120][1056,216]"/>
    <node index="3" text="" content-desc="Добавить" class="android.widget.ImageView" clickable="true" bounds="[24,2040][168,2200]"/>
  </node>
</hierarchy>
```

- [ ] **Step 2: Проверить, что фикстура не содержит токенов editor_triggers**

Run:
```bash
cd /home/claude-user/autowarm-testbench
grep -E "Добавить описание|Add description|Опубликовать|Upload|>Видео<|Прямой эфир|>Live<" tests/fixtures/yt_create_menu/shorts_camera.xml && echo "BAD: токен найден" || echo "OK: токенов editor_triggers нет"
```
Expected: `OK: токенов editor_triggers нет`.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/fixtures/yt_create_menu/shorts_camera.xml
git commit -m "test(wp134): фикстура разреженного dump камеры Shorts"
```

---

## Task 3: Soft-pass в `_tap_plus_and_verify` (основное изменение)

**Files:**
- Modify: `account_switcher.py::_tap_plus_and_verify` (ветка `if strict_verify and not hits:`, ~стр. 5040)
- Test: `tests/test_yt_create_menu_strict_verify.py`

- [ ] **Step 1: Написать падающие интеграционные тесты**

Добавить в `tests/test_yt_create_menu_strict_verify.py`:

```python
def _stub_with_fg(xml_path: Path, fg_pkg: str) -> _asw.AccountSwitcher:
    """Как _stub_switcher_with_dump, но с явным foreground-пакетом."""
    sw = _stub_switcher_with_dump(xml_path)
    sw._detect_foreground_pkg = MagicMock(return_value=fg_pkg)
    return sw


def test_soft_pass_when_yt_foreground_on_shorts_camera(monkeypatch):
    """Камера Shorts (нет триггеров) + foreground=YouTube → _ok + событие."""
    monkeypatch.delenv("YT6_ACCEPT_NONMENU_FOREGROUND", raising=False)
    sw = _stub_with_fg(FIX / "shorts_camera.xml", "com.google.android.youtube")
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert result.success is True
    assert result.final_step == "yt_6_create_menu"
    cats = [c.kwargs.get("meta", {}).get("category")
            for c in sw.p.log_event.call_args_list]
    assert "yt_create_menu_camera_direct" in cats


def test_soft_pass_off_falls_back_to_fail(monkeypatch):
    """Kill-switch OFF → legacy fail yt_create_menu_not_reached, даже при YT-fg."""
    monkeypatch.setenv("YT6_ACCEPT_NONMENU_FOREGROUND", "0")
    sw = _stub_with_fg(FIX / "shorts_camera.xml", "com.google.android.youtube")
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_no_triggers"


def test_no_soft_pass_when_foreground_is_launcher(monkeypatch):
    """Drift (foreground=лончер) → НЕ soft-pass, обычный fail.

    WP#87 Layer C отключаем (YT_CREATE_MENU_GUARD_ENABLED=0), чтобы изолированно
    проверить fg-гард нашей ветки: при fg != YouTube soft-pass не срабатывает.
    """
    monkeypatch.setenv("YT6_ACCEPT_NONMENU_FOREGROUND", "1")
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "0")
    sw = _stub_with_fg(FIX / "shorts_camera.xml", "com.sec.android.app.launcher")
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_no_triggers"
    cats = [c.kwargs.get("meta", {}).get("category")
            for c in sw.p.log_event.call_args_list]
    assert "yt_create_menu_camera_direct" not in cats


def test_happy_path_no_camera_event(monkeypatch):
    """Реальное меню (триггеры есть) → _ok без события камеры."""
    monkeypatch.delenv("YT6_ACCEPT_NONMENU_FOREGROUND", raising=False)
    sw = _stub_with_fg(FIX / "create_menu_open.xml", "com.google.android.youtube")
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert result.success is True
    cats = [c.kwargs.get("meta", {}).get("category")
            for c in sw.p.log_event.call_args_list]
    assert "yt_create_menu_camera_direct" not in cats
```

> **Mock-drift guard:** новая ветка вызывает `self._detect_foreground_pkg()` — в тестах он замокан через `_stub_with_fg`. Имя метода совпадает 1-в-1 с `account_switcher.AccountSwitcher._detect_foreground_pkg`; `self.p.log_event` — реальный метод `DevicePublisher` (в стабе MagicMock). Сверка имён обязательна (урок mock-proxy-drift, PR #52).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_create_menu_strict_verify.py -k "soft_pass or no_soft_pass or happy_path_no_camera" -v`
Expected: FAIL — `test_soft_pass_when_yt_foreground_on_shorts_camera` падает (нет события / fail вместо ok), т.к. soft-pass ещё не вшит.

- [ ] **Step 3: Вшить soft-pass в `_tap_plus_and_verify`**

В `account_switcher.py`, в ветке `if strict_verify and not hits:`, **сразу после** закрывающего блока premium-promo (после строки `return self._fail(... step=pb_step,)` premium-ветки) и **перед** строкой `fail_step = f'{final_step}_no_triggers'`, вставить:

```python
            # [WP #134] Остались ВНУТРИ YouTube (камера Shorts / иной create-экран),
            # но не на bottom-sheet «меню создания»? Это НЕ фатально: загрузка идёт
            # через Shell_UploadActivity (минует меню и галерею), а
            # _normalize_yt_state_pre_upload всё равно закроет этот экран. Аккаунт
            # уже подтверждён на yt_5. Soft-pass — даём отработать пути загрузки.
            # Drift (foreground != YouTube) сюда не попадает: его ловит Layer C
            # выше, а здесь дополнительно гард по fg.
            if _yt6_accept_nonmenu_foreground_enabled():
                fg = self._detect_foreground_pkg()
                if fg and fg == cfg['package']:
                    self.p.log_event(
                        'warning', 'yt_create_menu_camera_direct',
                        meta={'category': 'yt_create_menu_camera_direct',
                              'step': final_step,
                              'foreground_pkg': fg,
                              'shorts_camera_markers': _yt_is_shorts_camera(ui2)},
                    )
                    return self._ok(final_step, already_matched=already_matched)
```

- [ ] **Step 4: Запустить новые интеграционные тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_create_menu_strict_verify.py -k "soft_pass or no_soft_pass or happy_path_no_camera" -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_strict_verify.py
git commit -m "feat(wp134): soft-pass yt_6 при YT-foreground (камера Shorts) + телеметрия"
```

---

## Task 4: Регрессионный прогон YT-тестов

**Files:** —

- [ ] **Step 1: Прогнать весь набор YT/switcher тестов**

Run:
```bash
cd /home/claude-user/autowarm-testbench
python -m pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_create_menu_fg_guard.py tests/test_yt_premium_promo_dismiss.py tests/test_yt_post_switch_verify.py tests/test_account_switcher.py -q
```
Expected: всё PASS (новые + существующие). Премиум-приоритет и IG/TT-инвариант (`test_non_strict_verify_*`) не сломаны.

- [ ] **Step 2: Если есть pre-existing fails — зафиксировать, что они НЕ от нашего изменения**

Сравнить с зелёной базой из Task 0 Step 2. Любой fail, существовавший до правок, не блокирует (отметить в PR-описании). Наши тесты и затронутая ветка `_tap_plus_and_verify` должны быть зелёными.

---

## Task 5: PR + деплой в прод + smoke

**Files:** —

- [ ] **Step 1: Запушить ветку и открыть PR**

```bash
cd /home/claude-user/autowarm-testbench
git push -u origin feat/wp134-yt-shorts-camera-soft-pass
gh pr create --repo GenGo2/delivery-contenthunter \
  --title "WP#134: yt_6 soft-pass при камере YouTube Shorts (не TikTok)" \
  --body "Разведка опровергла премису #134: на записях 9025/9092/9108 — нативная камера YouTube Shorts, не TikTok. yt_6 strict_verify фатально падал, когда «+» открывает камеру вместо bottom-sheet, ДО устойчивого пути Shell_UploadActivity. Фикс: soft-pass при fg==youtube + телеметрия yt_create_menu_camera_direct + kill-switch YT6_ACCEPT_NONMENU_FOREGROUND. Спека/план: docs/superpowers. Тесты зелёные."
```
> Токен GenGo2 — в `~/secrets/github-gengo2.env`. При необходимости: `set -a; . ~/secrets/github-gengo2.env; set +a`.

- [ ] **Step 2: Прогнать `codex review` по диффу (практика перед merge)**

Run: `cd /home/claude-user/autowarm-testbench && git diff origin/main...HEAD | ~/.local/bin/codex review -`
Применить P1-фидбэк (если есть), коммитнуть, повторить до 0 P1. (bubblewrap-warning безобиден.)

- [ ] **Step 3: Merge PR (после твоего ок)**

```bash
gh pr merge --repo GenGo2/delivery-contenthunter --squash --delete-branch <PR#>
```

- [ ] **Step 4: Деплой в прод autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin main && git checkout main && git pull --ff-only
git log --oneline -1   # подтвердить, что наш коммит на месте
```
Подтвердить, что PM2-воркер публикаций читает этот путь: `pm2 describe autowarm | grep "exec cwd"` (урок pm2-dump-path-drift — должен быть `/root/.openclaw/workspace-genri/autowarm`).

- [ ] **Step 5: Рестарт воркера публикаций**

```bash
sudo pm2 restart autowarm --update-env
pm2 describe autowarm | grep -E "status|exec cwd"
```
Expected: `online`, cwd = prod-путь.

- [ ] **Step 6: Smoke — happy-path не сломан**

Re-queue 1 заведомо рабочую YT-выкладку (через `publish_queue` → pending, `publish_task_id=NULL`; dispatchPublishQueue создаст pt). Дождаться завершения, проверить, что публикация прошла как раньше (не появился ложный камер-soft-pass там, где было меню).

- [ ] **Step 7: Smoke — целевой кейс (если воспроизводится)**

Re-queue одну из затронутых выкладок-аккаунтов (@SmartEstateSpb / @DriveSAndDeliver / @AromaLuxCollection) через `publish_queue`. Проверить события задачи:
```sql
SELECT e->'meta'->>'category' cat, e->'meta'->>'shorts_camera_markers' markers, e->'meta'->>'foreground_pkg' fg
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events) e
WHERE pt.id=<new_task_id> AND e->'meta'->>'category' LIKE 'yt_create_menu%';
```
Ожидаемо: `yt_create_menu_camera_direct` + последующая загрузка через Shell_UploadActivity (status → awaiting_url/done). Если камеру-direct не воспроизвести — достаточно Step 6 (happy-path), а целевой кейс закрывается 24ч verify.

---

## Task 6: OpenProject + 24ч verify

**Files:** —

- [ ] **Step 1: Перевести WP#134 в «Тестирование» (id 9) + комментарий о деплое**

Через OpenProject API (token `~/secrets/openproject.env`, шейпы — в memory `reference_openproject_access`). Комментарий в домашнем стиле (Что было не так → Что сделано → Что осталось): что зашиплено (soft-pass + kill-switch), что проверить за сутки.

- [ ] **Step 2: 24ч verify (на следующий день)**

```sql
-- доля soft-pass и его исход
SELECT pt.status, COUNT(*)
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events) e
WHERE pt.platform='YouTube' AND pt.started_at > '<deploy_ts>'
  AND e->'meta'->>'category'='yt_create_menu_camera_direct'
GROUP BY 1;
-- общая динамика yt_create_menu_not_reached (должна снизиться)
SELECT date_trunc('day', started_at) d, COUNT(*)
FROM publish_tasks WHERE platform='YouTube' AND error_code='yt_create_menu_not_reached'
  AND started_at > NOW() - INTERVAL '5 days' GROUP BY 1 ORDER BY 1;
```
Acceptance: `yt_create_menu_camera_direct` появляется с последующим `done`/`awaiting_url`; `yt_create_menu_not_reached` снижается без всплеска downstream-фейлов. При регрессии — kill-switch `YT6_ACCEPT_NONMENU_FOREGROUND=0` + restart.

- [ ] **Step 3: Закрыть WP#134 → «Готово» (id 12)** после успешного verify; обновить memory.

---

## Self-review (выполнено автором плана)

- **Покрытие спеки:** §Логика soft-pass → Task 3; §Kill-switch + §детектор → Task 1; §Тесты (7 кейсов) → Task 1 (хелперы 1+5+пустой) + Task 3 (soft-pass/kill-off/drift/happy + IG-TT инвариант покрыт существующим `test_non_strict_verify_*`); §Наблюдаемость → Task 5/6 SQL; §Смоук → Task 5; §Деплой/откат → Task 5; §Сопутствующее (OpenProject) → Task 6 + уже сделанный корректирующий комментарий.
- **Плейсхолдеры:** `<PR#>`, `<new_task_id>`, `<deploy_ts>` — реальные runtime-значения, не плейсхолдеры дизайна. Кода без тела нет.
- **Согласованность типов/имён:** `_yt6_accept_nonmenu_foreground_enabled`, `_yt_is_shorts_camera`, `_YT_SHORTS_CAMERA_MARKERS`, событие `yt_create_menu_camera_direct`, env `YT6_ACCEPT_NONMENU_FOREGROUND` — употреблены единообразно во всех тасках и совпадают со спекой.
