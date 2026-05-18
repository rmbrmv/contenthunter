# WP #74 Round 2 — pre-merge live smoke evidence

**Date:** 2026-05-18
**Branch:** `feat/yt-foreign-fg-guard-20260518` (commit `da00d72`)
**Tester:** Claude (controller) + sonnet implementer subagents

## Что проверили

1. **Real-world parser fidelity** — `_parse_top_resumed_activity` против `dumpsys activity activities | grep -m1 topResumedActivity` на 4 идле устройствах raspberry 1 (testbench).
2. **End-to-end guard на реальном устройстве** — синтетический foreign foreground (Settings) → `_dismiss_foreign_foreground` → проверка escalation путей через реальный ADB.

## Реальный testbench output

| Device | topResumedActivity raw | parsed pkg | parsed act | classify |
|---|---|---|---|---|
| RF8Y80ZTVFZ (rasp 1) | `...com.sec.android.app.launcher/.activities.LauncherActivity...` | `com.sec.android.app.launcher` | `activities.LauncherActivity` | FOREIGN (idle home) |
| RF8Y90LBD1Y (rasp 1) | same | same | same | FOREIGN |
| RF8YA09S90H (rasp 1) | same | same | same | FOREIGN |
| RF8YA09SKYW (rasp 1) | (empty — device в weird state) | None | None | `probe_failed` |

Parser отработал на ВСЕХ четырёх корректно — реальный формат `ActivityRecord{...u0 pkg/.activity tN}` точно matches регулярку `topResumedActivity=ActivityRecord\{[^}]*?\s+([\w.]+)/([^\s/}]+)`. Случай empty dumpsys (RF8YA09SKYW) gracefully вернул `(None, None)` → `unrecoverable_reason='probe_failed'`.

## End-to-end synthetic smoke

**Сценарий:** RF8Y80ZTVFZ, открыли Settings (`am start -n com.android.settings/.Settings`), затем `_dismiss_foreign_foreground(source='manual_smoke')` через live publisher с реальным `self.adb = adb shell`.

**Результат** — последовательно:

```
[log info] cat=yt_foreign_foreground_detected meta={...top_package: 'com.android.settings'...}
(escalation a: skip-tap → empty UI dump, no tap)
(escalation b: KEYCODE_BACK ×2, after each re-probe — landed on launcher)
(escalation c: top_pkg='com.android.settings' IS in FOREIGN_FORCE_STOP_BLOCKLIST → halt)
[log error] cat=yt_foreign_foreground_unrecoverable_blocklist meta={...unrecoverable_reason: 'system_pkg_blocklist'...}

result = {
  'foreign_detected': True,
  'top_package': 'com.android.settings',
  'top_activity': 'Settings',
  'recovered': False,
  'escalation_steps': ['back_x1', 'back_x2'],
  'unrecoverable_reason': 'system_pkg_blocklist'
}
```

**Что валидировано:**
- ✅ Probe → parse → allowlist check работает с real-world output
- ✅ `yt_foreign_foreground_detected` event эмитится при foreign
- ✅ Kill-switch не сработал (env-flag не выставлен) → escalation проходит
- ✅ Skip-tap с empty UI → no match → переход на BACK (без crash)
- ✅ BACK×2 через `input keyevent KEYCODE_BACK` — real adb работает
- ✅ Blocklist sentinel — `am force-stop com.android.settings` НЕ выполнен (видно по отсутствию команды в логе), guard halt'нул на blocklist branch
- ✅ `yt_foreign_foreground_unrecoverable_blocklist` event с правильной meta-категорией

## Observation: Samsung launcher classification

`com.sec.android.app.launcher` (Samsung Home) сейчас НЕ в `FOREIGN_FORCE_STOP_BLOCKLIST` → если он окажется на foreground при guard-вызове, escalation дойдёт до **force-stop launcher + relaunch YT**.

- В prod это произойдёт ТОЛЬКО внутри `publish_youtube_short` (после `_normalize_yt_state_pre_upload` или перед fail-fast в `_select_gallery_video`) — на idle guard НЕ вызывается.
- Force-stop launcher = home-screen blink ~0.5s + Android respawn, далее `am start YT LAUNCHER` поднимает YT. В большинстве случаев это валидная recovery (YT упал post-launch).
- НО: force-stop системного launcher = heavy-handed. Symmetry с другими system pkgs (`com.android.systemui`, `com.android.settings`) предполагает добавить launcher в BLOCKLIST.

**Backlog item (не блокирует merge):** добавить `com.sec.android.app.launcher`, `com.android.launcher`, `com.android.launcher3`, `com.google.android.apps.nexuslauncher` в `FOREIGN_FORCE_STOP_BLOCKLIST`. Это превратит "force-stop launcher + relaunch YT" в "blocklist halt + fail-fast", что чище. Стоимость: ~5 LOC + 1 test. Может быть отдельным mini-PR после merge.

## Что НЕ проверили (требует более тяжёлой инфраструктуры)

- **Full publish_youtube_short e2e** — не запускали реальную YT публикацию (нужен публикабельный аккаунт + queue worker + видео на устройстве). Mitigation: 4 integration теста в Tasks 7-8 mockают `_dismiss_foreign_foreground` напрямую и проверяют call-site контракт.
- **Force-stop foreign + relaunch YT success path** — Settings в blocklist halted перед force-stop, так что branch `force_stop_and_relaunch` не выполнялся на real device. Mitigation: 3 unit-теста в `TestForeignForegroundEscalationForceStop` (mock-based) покрывают эту ветку.
- **Synthetic Samsung Account ForceLoginSamungAccountActivity** — не нашли способа триггернуть этот dialog искусственно (Galaxy Store сам решает когда показать). Будем ждать естественного рецидива в prod (24h verify).

## Acceptance for PR

- 36/36 unit tests green (включая 3 escalation-class тестов + 4 integration теста).
- Codex review: 0 P1.
- Live parse: 4/4 устройств корректно распарсены.
- Live escalation: BACK×2 + blocklist branch validated.
- Pre-existing prod failures: 14 на main (verified, не регрессия).

**Status:** READY TO PR.
