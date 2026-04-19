# T7 — Структурный аудит `/tmp/auto_public`

**Клон:** `/tmp/auto_public`, last commit `2aa9b4c` 2026-04-17.
**Стек:** Python 3, Airtest + Poco, cv2 (OpenCV), SQLAlchemy, dotenv, httpx. Celery-совместимо (celery_signals.py).

## Модули и размеры

```
auto_public/
├── main.py                     173 строки   — CLI + SocialMediaUploader оркестратор
├── remote_worker.py             ~90 строк   — отдельный entry (не дочитано)
├── celery_signals.py             28 строк   — Celery prefork/post handlers
├── by_images.py                174 строки   — **experimental** image-based TikTok uploader (cv2+Airtest Template)
├── uploader/
│   ├── base.py                 515 строк   — BaseUploaderService: connect+restart, init_poco, upload_video_template
│   ├── instagram.py            139 строк   — IG: plus_button → reels → content → caption → publish
│   ├── tiktok.py                95 строк   — TT: аналогично IG (+ stub switch_to_account → False)
│   ├── vk.py                    83 строки   — VK uploader
│   └── youtube.py               84 строки   — YouTube uploader
├── llm_providers/
│   ├── anthropic.py              -         — Anthropic API client
│   └── open_router.py           ~80 строк  — OpenRouter API client (default model: anthropic/claude-3.5-sonnet)
├── services/
│   └── llm_manager.py          136 строк   — **LLMManager**: screen→LLM→touch/confirm/alert
├── scheduler/
│   └── scheduler_autopublic.py   -         — Celery beat or custom scheduler
├── prompts/
│   ├── system_base.txt            -
│   └── system_rare.txt          ~35 строк  — LLM system prompt для screen-state recovery
├── utils/
│   ├── database.py               -         — engine + session factory
│   ├── models.py                 -         — ORM
│   └── draw.py                   -         — cv2.circle overlay для Telegram-alert screenshots
├── elems/                        -         — pre-recorded UI element screenshots
└── images/                       -         — reference images для Template matching
```

## Ключевые паттерны

### 1. `BaseUploaderService.upload_video_template` (base.py:440-520)

```python
def upload_video_template(self, device_id, s3_url, caption, username,
                          package_name, device_uri, use_poco=True):
    connect_device(device_uri or f"Android:///{serial}")
    if G.DEVICE and G.DEVICE.adb:
        self.adb = G.DEVICE.adb
        self.android_user = self.detect_android_user()

    local_video = self._download_video(s3_url)
    self._push_to_device(serial, local_video, "/storage/emulated/0/DCIM/Camera/")

    self.connect_and_restart_app(device_id=serial, device_uri=..., package_name=...)
    if use_poco:
        self.init_poco(device_id=device_id)

    if username and hasattr(self, 'switch_to_account'):
        if not self.switch_to_account(username):
            self.logger.warning(f"Could not switch to account {username}, continuing anyway...")
        sleep(2)

    try:
        self._perform_platform_upload_steps(caption)
    except (TransportDisconnected, JSONDecodeError):
        self._restart_uiautomator(serial)
        self.init_poco(device_id=serial)
        self._perform_platform_upload_steps(caption)
    # …cleanup…
```

**Что тут хорошо:**
- Универсальный template — платформы переопределяют только `_perform_platform_upload_steps(caption)` (instagram.py:85, tiktok.py:40)
- **`connect_and_restart_app`** — чёткая границa state-reset (stop_app + start_app + 8s settle) **до** UI-операций
- **Poco retry при TransportDisconnected** — self-healing против Airtest-Poco разрыва соединения
- `switch_to_account` используется, но не критичен (warning on fail, continuing anyway)

**Что плохо для farming-контекста:**
- Это **publishing**, не farming. Нет scroll/like/comment-примитивов — все в humanize_with_coords.py из autowarm_worker.
- Нет watch_count / like_every логики.

### 2. `LLMManager.handle_step(description)` (services/llm_manager.py:33-76)

```python
def handle_step(self, description: str, do_retry: bool = True) -> bool:
    snapshot_result = snapshot(filename=self.temp_file_path)
    self._screen_resolution = snapshot_result['resolution']

    with open(SYSTEM_PROMPT, 'r') as f:
        system_prompt = f.read()
    prompt = self._prompt.format(description=description)
    response = self.llm_provider.generate(
        image_path=self.temp_file_path, prompt=prompt, system_prompt=system_prompt)

    for command_call in response.splitlines():
        command, arguments_raw = command_call.strip()[:-1].split('(')
        arguments = [arg.strip() for arg in arguments_raw.split(',') if arg.strip()]

        if command == 'confirm':
            return True
        self._handle_command(command, arguments)  # → touch / alert

    if not do_retry:
        return False
    return self._retry_step(description, response)
```

**System prompt** (prompts/system_rare.txt):
> You are an automation agent responsible for publishing videos on social media platforms. Your only output is function calls — one per line, no explanations.
> 
> **Available functions:**
> - `touch(x, y)` — tap relative coords ∈ [0.0, 1.0]
> - `confirm()` — screen is clean, proceed
> - `alert(comment)` — save screenshot, Telegram notify manager

**Logic:**
- Если в экране popup/permission/ad — LLM вызывает `touch` + `alert`
- Если clean — LLM вызывает `confirm()` → handle_step возвращает True
- Если не распознал — fallback → `alert` в Telegram group

**Практическая ценность для нас:**
- Точно подходит для **unknown-screen recovery** (которое мы уже начали в publisher.py для IG highlights empty-state через `_is_ig_highlights_empty_state` + `_reopen_ig_reels_via_home`)
- Генерализует подход: вместо написания новых regex/image-темплейтов на каждый новый IG-редизайн, LLM classifies + prescribes touch-action
- **Cost:** ~1 claude-3.5-sonnet vision call per recovery attempt × 2 attempts = ~$0.01-0.02 на recovery

### 3. `by_images.py` (174 строки) — image-based publisher

Самостоятельный minimal TT uploader. Делает:
1. Download s3 video → local mp4
2. Extract first frame via cv2.VideoCapture
3. Crop middle + resize → save as reference image
4. Push video to device
5. stop_app / start_app / sleep 5
6. **Полностью image-based** flow:
   ```python
   plus_btn = Template("plus_btn.png", threshold=0.8)
   content = Template("resized.png", threshold=0.8)
   continue_btn = Template("continue_btn.png", threshold=0.8)
   description_box = Template("description_box.png", threshold=0.9)
   publish_btn = Template("pub.png", threshold=0.8)
   wait(plus_btn, timeout=30); touch(plus_btn)
   wait(content, timeout=30); touch(content)
   …
   ```

**Уникальность:** использует **actual video first-frame** как reference image для «найти мой контент в галерее» — очень умный трюк. Избегает проблемы «какой из 50 видео в галерее — наш».

**Ценность для farming:** ограниченная (публикация видео — не фарминг), но **идея first-frame-as-template** переносима: если нужно тапнуть на конкретный пост в IG feed (в свой профиль из swap'ера) — можно использовать его screenshot как identifier.

### 4. `_restart_uiautomator` (base.py:97-116)

```python
def _restart_uiautomator(self, device_id):
    self._kill_conflicting_processes(device_id)
    self._run_adb(device_id, [
        "shell", "am", "instrument", "-w",
        "com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner",
    ])
    sleep(2)
```

Хард-ресет UIAutomator-helper процесса на устройстве. Используется когда Poco/Airtest теряет связь. У нас аналогов нет — наш стек на raw ADB, но **если мы захотим Poco или Airtest**, нам понадобится этот pattern.

## Сильные стороны (для нашего проекта)

| Паттерн | Файл | Ценность |
|---|---|---|
| `connect_and_restart_app(stop_app + start_app + sleep 8)` | base.py:211-231 | **HIGH** — прямой фикс T2 account-read fails |
| `LLMManager.handle_step` + system_rare.txt prompt | services/llm_manager.py + prompts/ | MEDIUM-HIGH — generalize unknown-screen recovery |
| Template retry при TransportDisconnected | base.py:493-498 | LOW (нужен Poco) |
| `_restart_uiautomator` | base.py:97-116 | LOW (нужен Poco) |
| first-frame-as-template трюк | by_images.py | LOW — нишевый |
| Poco init с force_restart (base.py:233-258) | | LOW (нужен Poco) |

## Слабые стороны

1. **Автоматизации account-switching почти нет.** IG — требует pre-configured COORDS+ACCOUNT_COORDS (stub), TT — `return False`. Их модель — «1 device = 1 account» как у autowarm_worker.

2. **Нет daily-модулей для farming.** Весь код — про публикацию. Для 10-day прогрева аккаунтов нет ничего.

3. **Poco-зависимость.** Чтобы использовать их `upload_video_template`, нужен полный Airtest+Poco+uiautomator стек. Большой вес, заметное время init на каждый запуск.

4. **LLM-зависимость от OpenRouter.** Хардкод в `services/llm_manager.py:16` на OpenRouterAPI. Легко адаптируемо к Anthropic SDK напрямую (наш контекст), но нужен env var OPENROUTER_API_KEY → переход на ANTHROPIC_API_KEY.

## Итог T7 (reuse-кандидаты)

| Приоритет | Кандидат | Effort | Зависимости |
|---|---|---|---|
| **HIGH** | `connect_and_restart_app` pattern (force_stop + start + 8s) | S (1 день) | только ADB — вырвать легко |
| **MED-HIGH** | LLM-based screen-state recovery (адаптация `LLMManager` + `system_rare.txt`) | M (3-4 дня) | Anthropic SDK (уже есть) + cv2 snapshot |
| **MED** | `_perform_platform_upload_steps` как template method pattern (рефактор publisher.py на платформо-зависимые overrides) | L (рефактор) | — |
| LOW | Poco init + `_restart_uiautomator` | M | Airtest+Poco |
| LOW | `by_images.py` first-frame-as-template трюк | S (если понадобится) | cv2 |

**Главный кандидат:** **LLM-based screen-recovery**. Паттерн уже проверен в проекте на чужой практике, наша существующая «handler per screen» стратегия в publisher.py (`_is_ig_highlights_empty_state`, `_reopen_ig_reels_via_home`) хорошо дополнится LLM-fallback'ом для неизвестных экранов.

Вторичный — `connect_and_restart_app`, но этот же кандидат мы уже определили в T6 (через `_cleanup_device`). Просто дублируется как сильный сигнал.
