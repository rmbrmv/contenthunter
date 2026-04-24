# Evidence: S3 bucket policy для новых артефактов

**Дата:** 2026-04-24
**Задача:** T4 плана publish-tasks-s3-artifacts-20260424

## Проверка — эталонный screencast URL

```
$ curl -I https://save.gengo.io/autowarm/screenrecords/instagram/task906_fail_screenrec_906_1777012098.mp4
HTTP 200
Content-Type: video/mp4
```

## Test upload — новые prefix'ы

PNG и XML залиты через `publisher.upload_artifact_to_s3` с keys:
- `autowarm/screenshots/instagram/task9999_tmpezkdc4um.png`
- `autowarm/ui_dumps/tiktok/task9999_tmpvbej_rs0.xml`

```
$ curl -I https://save.gengo.io/autowarm/screenshots/instagram/task9999_tmpezkdc4um.png
PNG: HTTP 200  CT=image/png

$ curl -I https://save.gengo.io/autowarm/ui_dumps/tiktok/task9999_tmpvbej_rs0.xml
XML: HTTP 200  CT=application/xml
```

XML-контент читается:

```
$ curl https://save.gengo.io/autowarm/ui_dumps/tiktok/task9999_tmpvbej_rs0.xml
<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node/></hierarchy>
```

## Вывод

Bucket `1cabe906ea6e-gengo` через CDN `save.gengo.io` принимает и отдаёт public-read для любых ключей под `autowarm/*`. Дополнительной policy-настройки не требуется — текущая настройка (та же, что для screenrecords) покрывает новые prefix'ы автоматически.

Content-Type возвращается корректный (берётся из `ExtraArgs`), браузер будет открывать .png inline и .xml как текст.

Проверять legacy-ссылки `/screenshots/*` и `/ui_dumps/*` не стал — они фоллбэк через express-static и работают только пока файлы живы в `/tmp/`; это ожидаемое поведение.
