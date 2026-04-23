# T3 — Phone #171 Preflight (IG/TT/YT)

**Date:** 2026-04-23
**Method:** `account_revision.py` re-run после ручных правок user'а (T1) + ручная верификация TT через ADB
**Full JSON:** `/tmp/revision-171-preflight-t3.json`
**Full log:** `/tmp/revision-171-preflight-t3.log`

## Per-platform status

### Instagram — ✅ READY

```
status=found count=2 current='ivana.world.class'
accounts=['ivana.world.class', 'born.trip90']
```

Оба IG-аккаунта корректно обнаружены через switcher. Own-profile state подтверждён. Farming на IG с #171 можно запускать без дополнительных fix'ов.

### TikTok — ❌ NOT READY (app_not_launched)

**Симптом:** После T1 (ручное ре-логирование user'ом) TT теперь не переходит дальше `SplashActivity`. Revision делает 3 aggressive retry (force-stop → `am start` → wait for ViewPager), все 3 fail'ятся с `deadline_exceeded` и `launcher foreground`.

**Ручная верификация:**

```
adb shell am force-stop com.zhiliaoapp.musically
adb shell monkey -p com.zhiliaoapp.musically -c android.intent.category.LAUNCHER 1  # OK
adb shell dumpsys window | grep mCurrentFocus
  → com.zhiliaoapp.musically/com.ss.android.ugc.aweme.splash.SplashActivity  # stuck
# После 20+ сек всё ещё в SplashActivity; uiautomator dump: "could not get idle state"
```

**Вероятные причины (от более к менее вероятной):**
1. Pending OAuth/login flow после ручного ре-логина не закрыт (app подгружает токен из сервера, висит на сетевом запросе)
2. Network block (TT в прод-proxy RU может быть блокирован без VPN)
3. App crash silently (app-процесс жив но activity hang)

**Решение:** оставляем до первой farming-задачи на TT — testbench словит `app_not_launched` error, triage classify как `tt_splash_hang`, agent_diagnose предложит hypothesis (например, подключить pcap / проверить network reachability). Это и есть raison d'être testbench.

### YouTube — ❌ NOT READY (anchor_suspicious_position)

**Симптом:**

```
[switcher-ro] YouTube: anchor at y=313 is suspiciously high (header_y_max=260) — likely false positive
status=error reason=anchor_suspicious_position platform=YouTube anchor_y=313 header_max=260
```

Switcher guard-rail срабатывает: нашёл anchor на y=313, но header_y_max=260, → anchor ниже границы header'а → классифицирует как false positive.

Известный баг #171 (per memory `project_revision_phone171_backlog.md`): bottom-nav `(972, 2320)` не открывает профиль. Текущее поведение — новая манифестация того же класса проблемы (другое location для anchor).

**Решение:** аналогично TT — testbench словит на первой YT-задаче, agent_diagnose предложит расширение `header_y_max` boundary в `account_switcher.py` или alternative path через Settings-activity (я уже нашёл `am start com.google.android.youtube/.app.application.Shell_SettingsActivity` → Аккаунт → Смена аккаунта — работает как backup path).

## Summary

| Платформа | Preflight | Go/No-go для MVP orchestrator     |
|-----------|-----------|------------------------------------|
| IG        | ✅ found  | GO — включать в round-robin сразу  |
| TT        | ❌ hang   | NO-GO на preflight, но testbench запускать всё равно — нужна эвиденция для auto-fix loop |
| YT        | ❌ error  | NO-GO на preflight, но testbench запускать всё равно — нужна эвиденция для auto-fix loop |

## Implication для orchestrator

MVP поведение farming-orchestrator (T7):
- Round-robin IG → TT → YT (как запланировано)
- Первые TT/YT запуски будут failed — OK, они станут первыми investigations
- Auto-pause threshold: 10 подряд ban_detected (не trigger на `app_not_launched` / `anchor_suspicious`)

## Ссылки

- Dumps (IG ok): `/tmp/autowarm_revision_dumps/switch_revision-RF8Y90GCWWL-1776955978_*instagram*.xml`
- Dumps (TT splash-hang): `/tmp/autowarm_revision_dumps/switch_revision-RF8Y90GCWWL-1776956041_ro_1_launch_tiktok_a1_1776956081.xml`
- Dumps (YT suspicious anchor): в /tmp/autowarm_revision_dumps/ по timestamp 1776956_*.xml
