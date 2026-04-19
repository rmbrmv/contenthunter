# T2 — Deep-dive: account-read failure mode (77 из 178 error-событий)

## Наш код, который эмитит сообщение

**Файл:** `/root/.openclaw/workspace-genri/autowarm/warmer.py`
**Метод:** `verify_and_switch_account()` :730-772

```python
def verify_and_switch_account(self) -> bool:
    self.log_event('info', f'Проверка аккаунта: ожидаем @{self.account}')
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # секунд

    for attempt in range(1, MAX_RETRIES + 1):
        if self.platform == 'Instagram':
            current = self.get_current_instagram_account()  # :426
        elif self.platform == 'TikTok':
            current = self.get_current_tiktok_account()     # :556
        elif self.platform == 'YouTube':
            current = self.get_current_youtube_account()    # :635

        if current is not None:
            break

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
        else:
            self.log_event('error',
                f'Не удалось прочитать аккаунт {self.platform} после {MAX_RETRIES} попыток — задача прервана')
            return False
    …
```

**Цена первой попытки (при False):** 3 × (tap + uiautomator dump + 5s sleep) ≈ 15-20 секунд, на выходе — failed task.

### Как получается current для каждой платформы

| Платформа | Метод | Fallback стратегий | Строки |
|---|---|---:|---|
| Instagram | `get_current_instagram_account` | **3 regex**: `content-desc=".'s profile"`, `action_bar_title`, `text+bounds.y<300` | warmer.py:426-457 |
| TikTok | `get_current_tiktok_account` | **1 regex**: `text="@([a-zA-Z0-9._]+)"` (первое совпадение) | warmer.py:556-571 |
| YouTube | `get_current_youtube_account` | (аналогично IG, не дочитано) | warmer.py:635-728 |

**Структурная слабость TikTok:** единственный regex `text="@..."` — ловит **первый** `@username` на экране. Если профиль ещё не загрузился (реклама, splash, popup «разрешите уведомления»), в UI могут быть чужие @ (комментарии стрима, саджесты «возможно знакомые»). Это объясняет почему TT — топ-1 по account-read fails (32 случая).

## Реальный кейс (task 127, TikTok day 1, account `@forsal32`)

```
16:55:02 → running: Запуск прогрева дня 1
16:55:02 День 1 · TikTok · forsal32
16:55:35 Проверка аккаунта: ожидаем @forsal32
16:56:26 Не удалось прочитать аккаунт TikTok после 3 попыток — задача прервана   (+51 сек)
16:57:39 Запись экрана фарминга (screenrecord URL)
16:57:40 → failed: Аккаунт @forsal32 не активен и не удалось переключиться
16:57:40 Аккаунт @forsal32 не совпадает с активным — задача прервана
```

**Интервал 51 сек** между start и "3 попытки не хватило": 3 × (tap 1030 2270 → sleep 2 → uidump) + 2 × sleep(5) ≈ 21 + 10 = 31с, остальное — overhead ADB. UI-dump вернулся, но regex не нашёл.

## Реальный кейс (task 129, Instagram day 1, account `@elitecornersspb`)

```
12:49:02 День 1 · Instagram · elitecornersspb
12:49:38 Проверка аккаунта: ожидаем @elitecornersspb
12:50:25 Не удалось прочитать аккаунт Instagram после 3 попыток — задача прервана
12:50:32 → failed: Аккаунт @elitecornersspb не активен
12:51:02 → running: Запуск прогрева дня 1        ← AUTO-RETRY ВСЕЙ ЗАДАЧИ
12:51:45 Проверка аккаунта: ожидаем @elitecornersspb
12:51:53 ✅ Instagram аккаунт верный: @elitecornersspb    ← PASS на 2-м старте
12:52:45 Фаза поиска: ['премиум класс спб', 'недвижимость санкт петербург']
12:53:12 Лайк не подтверждён (Instagram) — пропускаем
…
```

**Критичный паттерн:**
- **Первый запуск провалился**, второй автоматический перезапуск задачи — **успешен** через 37 секунд после первого fail.
- Значит проблема не в «аккаунт не активен» — он активен. Проблема в том, что **UI первого запуска был в транзитном состоянии** (app cold-start / splash screen / ad overlay) когда `get_current_instagram_account()` сделал dump.
- Задача 129 имеет 69 events и status=failed. Из событий видно, что после успешного account-read она таки прогрелась и дошла до лайков — значит что-то ниже убило её (вероятно watchdog, см. T3) или `Лайк не подтверждён` 10+ раз подряд.

## Сравнение с чужими репо

### `autowarm_worker`

**Файлы:** `app/modules/{ig,tiktok,yt}/day1.py` — по 22-61 строке.
**Подход:** НЕТ account-verification на уровне daily-модулей. Всё делегировано в `HumanizeActions`:

```python
def FirstDay(device_uri, subject=None, social_network="ig"):
    h = HumanizeActions(device_uri)
    h.close_social_media()                    # force-close апп перед стартом
    return h.run_search_and_watch_flow(...)
```

**Архитектурная презумпция:** **1 device = 1 account**. Если устройство пришло на обработку — значит нужный аккаунт уже активен. Проверки логина/username нет вообще.

**Плюс:** zero false-positive на account-read. Всегда начинают от чистой app-restart (`close_social_media()`).
**Минус:** если устройство случайно с не тем аккаунтом — прогрев пойдёт по чужому аккаунту, без алертов.

### `auto_public`

**Файлы:** `uploader/{instagram,tiktok}.py` (139+95 строк), общий `uploader/base.py` (515 строк).
**Подход:**
- **Perform-upload template:** `connect_and_restart_app(package_name)` **до** проверки аккаунта (base.py:211-231) — **stop_app + start_app + sleep 8s**.
- `switch_to_account(username)` вызывается опционально (base.py:483):
  ```python
  if username and hasattr(self, 'switch_to_account'):
      if not self.switch_to_account(username):
          self.logger.warning(f"Could not switch to account {username}, continuing anyway...")
      sleep(2)
  ```
- **IG switch_to_account** (instagram.py:47-83): требует **pre-configured COORDS{my_acc, choose_acc, home_btn}** + `ACCOUNT_COORDS[username]` — если их нет, `return False`. В dump-версии все эти координаты = `None`, фактически работает **только** когда оператор предзаполнил.
- **TikTok switch_to_account** (tiktok.py:37-38):
  ```python
  def switch_to_account(self, username):
      return False
  ```
  **Заглушка.** В автоматическом виде они аккаунт не переключают.
- Используется **Poco** (AndroidUiautomationPoco) для UI-детекции — более стабильный API, чем наш raw regex.
- `_restart_uiautomator` (base.py:97-116) — хард-ресет uiautomator через adb shell am instrument, когда Poco фейлит.
- `init_poco` (base.py:233-258) — 2 попытки Poco init с force_restart, hard fallback.

**Сильная сторона auto_public для нашей задачи:**
- `connect_and_restart_app` — force-close + start app + **8 сек settle** **до** любой UI-операции. У нас такого wrapper'а нет; мы идём на профиль сразу после ADB-тапа.
- Poco как альтернатива нашему regex на XML dump — принципиально другой API, устойчивее к мелким сдвигам вёрстки.

**Слабая сторона auto_public для нашей задачи:**
- Account-switch у них почти не автоматизирован. Наш подход (reverse-engineering switcher через regex) технически сложнее и лучше.

## Диагноз + recommendations для реюза

### Root cause account-read fails (77 случаев)

1. **Отсутствие state-reset между retries** в `verify_and_switch_account`. 3 попытки × 5s без force-restart app → если IG/TT/YT висит в splash/ad/onboarding, никакие 3 retries не помогут.
2. **Слишком узкий window** (15-20с) для первой «встречи» с приложением после его запуска pm2-планировщиком. Например, IG app cold-start на emulated-устройстве легко берёт 20-25с до показа profile tab.
3. **Regex-зависимость** для TikTok — первый `text="@..."` часто не username профиля.

### Reuse-кандидаты на этот failure mode

| Идея | Откуда | Gain | Effort |
|---|---|---|---|
| **Force `stop_app + start_app + sleep 8` перед account-check** | `auto_public/uploader/base.py:229-231` | high — устраняет источник splash/ad overlay | S (1 день, без Poco-зависимости) |
| **Daily-module архитектура «1 device = 1 account»** (переложить account-verification в UPFRONT preflight вне retry-loop) | `autowarm_worker/app/modules/*/day1.py` | medium — снижает false-positive, но ломает multi-account-per-device модель (которую мы используем) | L — рефактор |
| **Poco вместо raw-regex для IG/TT/YT account read** | `auto_public/uploader/base.py:233-258` (init_poco) + `_restart_uiautomator` | medium-high — устойчивее к сдвигам UI | M — интеграция Airtest/Poco в существующий ADB-подход |
| **Add `meta.category` к warmer log_event** (на account_read_fail, account_mismatch, account_switch_success/fail) | не из чужих репо, наш собственный баг | high — без этого нет monitoring | S (0.5 дня) |

**TOP приоритет:** force-restart-app wrapper — одним изменением вероятно решает большую долю «3-retries-not-enough» кейсов. Образец прямо в auto_public/base.py.

**Вторичный приоритет:** добавление `meta.category` во все warmer.log_event — без этого метрики/алерты на farming невозможны (мы увидели это в T1).
