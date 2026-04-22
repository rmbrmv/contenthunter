# Launch-failures fixture triage — 2026-04-22

**План:** `.ai-factory/plans/publish-launch-failures-fix-20260422.md`
**Инструмент:** `/home/claude-user/autowarm-testbench/tools/fixture_triage.py`
**Phone #19:** `RF8YA0W57EP` (Samsung SM-A175F, Android)
**Window:** последние 6 часов 100% fail-rate (с 01:34 UTC 2026-04-22)

## Raw triage table

```
| task | platform  | error_code             | last_ui_pkg (actual fg)        | last_step  |
|------|-----------|------------------------|--------------------------------|------------|
| #638 | TikTok    | tt_app_launch_failed   | com.sec.android.app.launcher   | tt_1_feed  |
| #658 | YouTube   | yt_app_launch_failed   | com.sec.android.app.sbrowser   | yt_1_feed  |
| #659 | Instagram | ig_camera_open_failed  | com.instagram.android          | open_camera|
| #670 | TikTok    | tt_app_launch_failed   | com.sec.android.app.launcher   | tt_1_feed  |
| #671 | YouTube   | yt_app_launch_failed   | com.sec.android.app.sbrowser   | yt_1_feed  |
| #682 | Instagram | ig_camera_open_failed  | com.instagram.android          | open_camera|
```

## Diagnosis per platform

### YT (`yt_app_launch_failed`) — foreground=`com.sec.android.app.sbrowser`

**Root cause (2/2 confirmed):** Samsung Browser Custom Tab (`com.sec.android.app.sbrowser/.customtabs.CustomTabActivity`) остаётся поверх YT task.

Что видит `_foreground_pkg()` (account_switcher.py:1389): `package="com.sec.android.app.sbrowser"` в uiautomator XML. Не совпадает с target `com.google.android.youtube` → все 3 попытки `am start` возвращают этот же pkg → fail.

**Manual reproduction (2026-04-22 ~05:50 UTC):**
```
adb shell am start -W -n com.google.android.youtube/...WatchWhileActivity
>>> Activity: com.sec.android.app.sbrowser/.customtabs.CustomTabActivity
>>> LaunchState: HOT
>>> Warning: Activity not started, its current task has been brought to the front
```

`am force-stop com.google.android.youtube` НЕ помогает — Custom Tab живёт в sbrowser-task.

**Почему всплывает:** вероятно, YT-публикатор (или предыдущая задача) открывал внешнюю ссылку (YouTube Studio consent / "Open in browser"), которая запустилась в Custom Tab. После publisher exit Custom Tab остался висеть в foreground'е. На следующем цикле (10 мин) новая задача видит sbrowser сверху.

**Fix scope (T4):** `_dismiss_blocking_overlays()` детектирует `com.sec.android.app.sbrowser` → KEYCODE_BACK → опционально `am force-stop com.sec.android.app.sbrowser`. Ожидаемый close rate: 100% YT-задач с этим foreground.

### TT (`tt_app_launch_failed`) — foreground=`com.sec.android.app.launcher`

**Root cause (2/2 confirmed):** TikTok не поднимается в foreground после `am start` — экран остаётся на домашнем экране (Samsung Launcher). В UI dump'ах видны иконки Galaxy Store, Samsung Free, Gemini, Netflix и т.п. — это стандартный launcher, НЕ TT.

**Не same как YT:** здесь нет overlay'а; реальный фокус — launcher. TikTok либо:
- падает (crash) сразу после launch → launcher вновь получает фокус,
- не имеет назначенной launch activity (неправильный class path в `UI_CONSTANTS.TikTok.launch_activity`),
- в процессе unused-clean-up system его killed (LMK — low memory killer).

**Manual reproduction (2026-04-22 ~05:55 UTC):**
```
adb shell am start -W -n com.zhiliaoapp.musically/com.ss.android.ugc.aweme.main.MainActivity
>>> Activity: com.zhiliaoapp.musically/com.ss.android.ugc.aweme.main.MainActivity
>>> LaunchState: HOT  (!) TikTok process уже живёт
>>> mCurrentFocus=com.zhiliaoapp.musically/...MainActivity (ok)
```

Manual запуск **работает**. В процессе-листинге phone #19 на момент проверки TikTok процесс присутствовал. Значит разница в контексте `am start` из publisher'а — возможно:
1. TikTok process fresh (был killed) → cold-launch через published activity = slow → `OPEN_APP_WAIT_S=4s` + `2*1.5=3s` + `3*1.5=4.5s` ≈ 11.5s недостаточно для cold-start'а на загруженной системе.
2. TikTok пробуждается, показывает splash, затем крашится из-за уже открытой SystemShareActivity (publisher.py:3913 — TikTok запуск через SystemShareActivity упоминается в evidence-trace задачи 670, см. log: `[05:15:21] 💓 [TikTok] TikTok: запуск SystemShareActivity`).

**Hypothesis:** TT-publisher'с sequence такой: `adb push media → am start SystemShareActivity → switcher` vs ожидаемый `am start MainActivity → switcher`. SystemShareActivity может закрываться → launcher остаётся foreground → switcher'ов `_open_app('tt_1_feed')` не может поднять MainActivity потому что task stack — в странном состоянии.

Подтверждение нужно: trace `am start` вызовов в TT-pipeline + проверить, что в момент `tt_1_feed` `am start` получил `LaunchState: WARM` или `COLD` (а не "not started, task brought front").

**Fix scope (T5b):**
- **Опция A:** до `am start MainActivity` в `_open_app` сделать `am force-stop com.zhiliaoapp.musically` когда предыдущий `last_ui_pkg == com.sec.android.app.launcher` (подозрение на сломанный task stack). Reset гарантированно даст cold-start.
- **Опция B:** увеличить `OPEN_APP_WAIT_S` для TT с 4s до 8s + добавить check после launcher-detection «retry через force-stop».
- **Опция C (включить в T4):** расширить `_dismiss_blocking_overlays` детектором `com.sec.android.app.launcher` как «unexpected foreground» → force-stop target + retry. Это универсальный подход.

Выбор — **C** (универсально), с fallback на **A** если C даёт false-positives.

### IG (`ig_camera_open_failed`) — foreground=`com.instagram.android`, sub-screen="Об аккаунте"

**Root cause (2/2 confirmed):** IG foreground правильный, но камера заблокирована полноэкранной **"Об аккаунте" (About this account)** страницей.

UI dump (task #682):
```
resource-id="com.instagram.android:id/action_bar_title" text="Об аккаунте"
text="sasha_shoook"        ← НЕ наш target inakent06
text="Дата присоединения"
text="Март 2014 г."
text="Местоположение аккаунта"
text="Российская Федерация"
```

`bottom_sheet_camera_container` присутствует в tree, но НЕ активен (под modal'ом). camera wait в publisher.py:2791-2976 крутится в цикле ожидая triggers `['REELS', 'Галерея', 'ПУБЛИКАЦИЯ']` которые никогда не появятся.

**Как мы туда попали:** гипотеза — после SA-fastpath `_tap_plus_and_verify` нажал (50, 160) (координаты `plus_button` для Instagram). На этом IG-layout (обновленная навигация 2026) в (50, 160) находится **информационная иконка ⓘ** action bar'а, а не "+". Тап открывает "Об аккаунте" просматриваемого аккаунта (`sasha_shoook` — какой-то random видимый в feed'е, НЕ наш target).

Чтобы проверить — смотрим `switch_682_ig_sa_fastpath_1776836206.xml` — это дамп ДО тапа "+". В нём должна быть видна info-icon на y=160.

**Fix scope (T5c):**
1. **Детектор "Об аккаунте" modal'а** в wait_for_ig_camera (publisher.py). Если видим `action_bar_title text='Об аккаунте'` (или 'About this account' / другие профиль-info tit'лы) → tap на back (`action_bar_button_back`) или KEYCODE_BACK. Continue loop.
2. **Шире:** после SA-fastpath добавить pre-camera check — если мы НЕ на expected post-tap экране (нет `modal_container` с camera widgets), сделать BACK и retry.
3. **LLM screen-recovery** уже integrated на attempt ≥3 (publisher.py:2890) — должен распознавать "Об аккаунте" как unknown + действовать. Проверить, почему для task #659/#682 он не пометил action=back.

**Coverage оценка:** закрытие IG-кейсов 100% если добавить детектор sub-screen'а; но нужна ещё fix на SA-fastpath plus button coords (см. ниже).

### Switcher telemetry bug (orthogonal)

Task 682: watchdog-fired event имеет `step="switcher: ig_2_profile_tab_fg_guard"` несмотря на то, что SA-fastpath уже закончился и идёт `open_camera` step. Это сбивает LLM-триаж (`evidence/publish-triage/ig_camera_open_failed-20260421-143849-task553.md` так и получил неправильную гипотезу «увеличить таймаут fg_guard»).

Fix — **T6**: `self.p.set_step('post-account-switch')` в `publisher._ensure_correct_account` после success-log_event, ИЛИ `set_step` внутри `_tap_plus_and_verify` в success-ветке.

## Chosen approach (T3)

| Error code | Phase 2 T4 (overlay dismiss) | Phase 3 T5 (platform-specific) | Phase 4 T6 (step reset) |
|---|---|---|---|
| `yt_app_launch_failed` | ✅ closes (sbrowser Custom Tab → BACK / force-stop) | — | — |
| `tt_app_launch_failed` | ✅ closes if T4 детектит launcher как "unexpected" + force-stop target (hypothesis C) | T5b residual: если C не полный, добавить force-stop target перед `am start` когда prev fg=launcher | — |
| `ig_camera_open_failed` | — (foreground правильный — IG) | ✅ T5c: детектор "Об аккаунте"/sub-screen → BACK + retry; пересмотр plus_button coords | ✅ T6: правильный step name в watchdog'е |

Expected after-rates:
- yt_app_launch_failed: 31 → ≤3 (от residual Custom Tab вариантов вне sbrowser).
- tt_app_launch_failed: 26 → ≤5 (зависит от глубины T5b).
- ig_camera_open_failed: 30 → ≤5 (sub-screen detector + plus_button fix).

## Scope adjustments

- **T4 расширяется:** детектит и `sbrowser` и `launcher` как blocking overlays; действие различное (force-stop sbrowser vs force-stop target app для launcher).
- **T5b становится меньше:** большая часть TT-решения уходит в T4. Residual T5b — `OPEN_APP_WAIT_S` adjustment (4s → 8s для TT, если после T4 ещё фейлы).
- **T5c не меняется:** IG "Об аккаунте" детектор + plus_button-coords audit.
- **T6 независим:** можно коммитить в C2 вместе с T4.

## Open questions — follow-up

1. Почему Custom Tab sbrowser не закрывается сам? Нужно проверить, какой модуль publisher'а его открывает (grep `CustomTab` / `browser intent`). Возможно, достаточно в этом модуле поменять target → `am force-stop` после close.
2. SA-fastpath `plus_button={'coords': (50, 160)}` — эти coords валидны для Galaxy S21 1080x2400; на SM-A175F (1080x2340 — небольшая разница) может быть offset. Сравнить с `switch_682_ig_sa_fastpath_*.xml` bounds для action bar на y=140-200 и проверить, не попадает ли (50, 160) в info-icon вместо plus.
3. В случае неэффективности force-stop sbrowser — fallback: `am start -n <YT main activity>` с флагом `--activity-clear-top --activity-new-task` может сработать напрямую.

## Run command reference

```bash
# Быстрый триаж свежих фейлов по error_code:
cd /home/claude-user/autowarm-testbench
python3 tools/fixture_triage.py --error-code yt_app_launch_failed --limit 3

# По конкретным task_id:
python3 tools/fixture_triage.py 670 671 682 -v

# С записью в файл:
python3 tools/fixture_triage.py 670 671 682 -o /tmp/triage.md
```
