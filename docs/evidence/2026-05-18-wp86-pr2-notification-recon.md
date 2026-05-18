# WP #86 PR2 — Notification Recon Evidence

**Date:** 2026-05-18
**Device tested:** RF8Y80ZTVFZ (Pi #1, port 15037, proxy 147.45.251.85)
**Phones also checked:** RF8Y90LBD1Y, RF8YA09S90H, RF8YA09SKYW

## Command run

```bash
adb -H 147.45.251.85 -P 15037 -s RF8Y80ZTVFZ shell \
  "dumpsys notification --noredact 2>/dev/null"
```

## TikTok (com.zhiliaoapp.musically)

There are **2 active "Загрузка завершена" (Upload complete) notifications** on the device.

Fields present:
- `android.title=String (Загрузка завершена)` — standard upload-complete notification
- `android.text=String (Смотреть публикацию)` — "View post" — **NO URL**
- `android.subText=null`
- `android.bigText` — not present
- `contentIntent=PendingIntent{...}` — URL is embedded inside PendingIntent, NOT accessible from dumpsys output

**Conclusion:** TikTok upload-complete notifications do NOT expose a URL in `dumpsys notification` output. The video URL is only embedded in the `contentIntent` PendingIntent object (which is an opaque reference to an Android Intent — not readable from shell).

## Instagram (com.instagram.android)

Active notifications on device:
- "Новый подписчик" (New follower) notification
- Fields: `android.title`, `android.text`, `android.bigText`, `android.subText` — contains username but NO URL
- No publish-complete/upload-complete notifications visible

## YouTube (com.google.android.youtube)

No active post-upload notifications. Channel metadata shows:
- `UploadNotifications` channel exists (Уведомления о загрузке видео)
- `importance=NONE userSet=true` — **YouTube notifications are DISABLED by the user** on this device

## Cross-device scan

Scanned RF8Y80ZTVFZ, RF8Y90LBD1Y, RF8YA09S90H, RF8YA09SKYW for any `https://` in notification text fields excluding system URIs. Result:
- Some SMS/messaging notifications containing promotional URLs (Home Credit, ALTEL)
- **Zero TikTok/Instagram/YouTube video URLs found**

## Conclusions

1. **A2 via dumpsys notification will NOT reliably capture URLs** for TT/IG/YT in current form. The platforms use PendingIntents, not plain-text URLs in notification extras.

2. **TikTok upload-complete notification IS fired** — so there IS a signal that upload completed. Text = "Смотреть публикацию" / "Upload complete". This could be used as a timing signal (not URL capture).

3. **YouTube notifications appear disabled** on at least one tested device.

4. **Implication for PR2 A2:** The `_capture_via_notifications` helper will compile and execute, but will return `None` in practice because no specific URL will be found in `dumpsys notification` output. This is acceptable — the code infrastructure is ready, and if TikTok ever starts embedding URLs in notification text (observed in some regional TikTok versions), A2 would activate automatically. Kill-switch `URL_CAPTURE_USE_NOTIF=0` is available if ADB overhead is a concern.

5. **A1 wave-retry** (3×45s) remains the primary value-add of PR2 for TikTok URL capture improvement.

## Recommendation

- Implement A2 as planned (infrastructure cost is low: 1 `dumpsys notification` call ≈ 0.5s)
- Document expected A2 success rate = ~0% in current TT/IG/YT versions
- A1 remains primary value — ensure wave-retry logic is correct
- Consider adding notification-title match ("Загрузка завершена") as timing signal for future PR3+ if needed
