# KotoPotok — контент-бот 

Автономный бот, который сам находит смешные моменты с людьми, видео/фото котов и виральные **вебмы** из **открытых бесплатных источников**, публикует их в Telegram-канал по расписанию и аккуратно подмешивает партнёрские ссылки.

Работает без твоего домашнего компьютера: достаточно запустить его один раз в бесплатном облаке. Управление — из Telegram с телефона.

## Что умеет

- публикует смешные моменты с людьми и видео/фото котов из **Pexels** и **Pixabay** (бесплатные ключи);
- публикует вебмы из **Wikimedia Commons** без ключа и с соблюдением лицензии/авторства;
- смешивает три типа контента по весам: коты / смешное / вебмы — меняется командой `/mix`;
- не повторяет уже опубликованное — база `data/bot.db`;
- случайный интервал, чтобы посты не выглядели роботизированно;
- активные часы публикации (например, только с 07:00 до 23:00 по Москве);
- партнёрские ссылки раз в N постов;
- команды управления в личке боту: `/status`, `/now`, `/pause`, `/resume`, `/interval`, `/stats`, `/sources`;
- `/health` и `/stats` endpoint'ы для мониторинга и автоперезапуска;
- **DRY_RUN** и **MOCK_MODE** для проверки без ключей и без Telegram.

> Важно: доход не гарантирован. Сначала канал нужно набрать подписчиков, потом подключать Telega.in, партнёрки или прямые рекламные посты. Бот делает рутину, а не «печатает деньги».

---

## Быстрый старт локально

### 1. Python

Нужен Python 3.10+. У тебя уже стоит Python 3.15 — подойдёт.

### 2. Создай Telegram-бота и канал

1. Напиши [@BotFather](https://t.me/BotFather) → `/newbot` → получи токен.
2. Создай канал, например `КотоПоток`.
3. Добавь бота в канал как **администратора** с правом публиковать сообщения.
4. В `.env` укажи:
   - `TELEGRAM_BOT_TOKEN=...`
   - `TELEGRAM_CHANNEL_ID=@your_channel`
5. `TELEGRAM_ADMIN_ID` можно оставить пустым: напиши боту `/start` в личку — он запомнит твой ID.

### 3. Получи бесплатный ключ источника

- Pexels: https://www.pexels.com/api/ → `PEXELS_API_KEY`
- Pixabay: https://pixabay.com/api/docs/ → `PIXABAY_API_KEY`

Ключи нужны для котов и смешных моментов из Pexels/Pixabay. Вебмы берутся из Wikimedia Commons **без ключа**. Если заполнить оба ключа — бот будет чередовать Pexels и Pixabay и станет надёжнее.

### 4. Заполни `.env`

```powershell
cd "C:\Users\dxrko\Documents\Проект по умолчанию\content_bot"
Copy-Item .env.example .env
notepad .env
```

### 5. Проверь без публикации

```powershell
python app.py
```

В `.env` временно включи:

```env
DRY_RUN=1
MOCK_MODE=1
```

Бот будет писать в консоль, что **опубликовал** бы, но ничего не отправит. Когда всё ок — убери эти строки.

### 6. Запуск на домашнем ПК

```powershell
.\run_local.bat
```

---

## Настройка микса контента

В `.env`:

```env
CONTENT_MIX=cat:30,funny:40,webm:30
ENABLE_COMMONS_WEBM=1
FUNNY_QUERIES=funny moments|people laughing|funny dance|sports fail|kids playing
WEBM_QUERIES=funny video|funny cat|funny animals|funny animation|funny moments
WEBM_KEYWORDS=funny|cat|cats|kitten|fail|lol|comedy|meme|кот|коты|смешн|весел|прикол
MAX_WEBM_DURATION_SEC=120
```

- `cat:30,funny:40,webm:30` — примерно 3 кота, 4 смешных момента и 3 вебма из каждых 10 постов.
- `cat:0,funny:0,webm:100` — только вебмы, ключи Pexels/Pixabay не нужны.
- `cat:0,funny:100,webm:0` — только смешные моменты из Pexels/Pixabay, без вебмов.
- `cat:100,funny:0,webm:0` — только коты, как в первой версии.
- `FUNNY_QUERIES` — поисковые фразы для смешных роликов с людьми/ситуациями.
- `WEBM_KEYWORDS` — грубый фильтр релевантности, чтобы поиск не присылал случайные архивные ролики.
- `MAX_WEBM_DURATION_SEC` отсекает длинные ролики: бот берёт короткие виральные фрагменты.

Бот выбирает лёгкую transcode-версию вебма (обычно 480p/360p), чтобы уложиться в лимит Telegram 50 МБ. Если Telegram всё же не примет `.webm` как видео, бот автоматически отправит его документом — пост не пропадёт.

---

## Управление из Telegram

Напиши боту в личку:

| Команда | Что делает |
|---|---|
| `/start`, `/help` | справка |
| `/status` | состояние, следующий пост, источники |
| `/stats` | статистика и последние посты |
| `/now` | опубликовать прямо сейчас |
| `/pause` | остановить автопостинг |
| `/resume` | продолжить |
| `/interval 120` | задать интервал в минутах |
| `/mix cat:30,funny:40,webm:30` | изменить доли котов, смешного и вебмов |
| `/sources` | показать источники и поисковые запросы |

---

## Монетизация

В `.env` есть `PARTNER_LINKS` — JSON-массив:

```json
[
  {"title":"VPN для безопасности","url":"https://example.com/ref/YOUR_ID","note":"полезно в поездках"},
  {"title":"Хостинг для проектов","url":"https://example.com/ref/YOUR_ID2","note":"бесплатный старт"}
]
```

Каждые `AD_EVERY` постов добавляется одна ссылка. Не ставь `AD_EVERY=1` — канал быстро превратится в спам и потеряет аудиторию.

Когда будет 1000+ подписчиков, можно подключить:
- Telega.in / Sociate — продажа рекламных постов;
- партнёрские программы хостингов, VPN, антивирусов;
- собственный мерч/ссылки на полезные сервисы.

---

## Автономный запуск в облаке

### Вариант A. GitHub Actions (рекомендуется)

Самый простой бесплатный вариант: сервер не нужен, GitHub сам раз в 3 часа запускает `python -m app --once`, бот публикует один пост и сохраняет базу обратно в репозиторий. Подробная инструкция — в `deploy/GITHUB_STEPS.md`.

Коротко:

1. Создай **публичный** репозиторий `kotopotok` на GitHub.
2. Загрузи туда файлы из `kotopotok_github.zip` (включая папку `.github`).
3. В Settings → Secrets and variables → Actions добавь `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL_ID`.
4. Вкладка Actions → **Run workflow** — проверить первый пост вручную.
5. Дальше работает расписание: 07, 10, 13, 16, 19, 22 МСК.

В этом режиме Telegram-команды не работают — управляй через редактирование `.github/workflows/post.yml` и кнопку **Run workflow**.

### Вариант B. Fly.io (быстро)

1. Установи `flyctl`: https://fly.io/docs/hands-on/install-flyctl/
2. В папке `deploy`:
   ```powershell
   fly launch --no-deploy
   fly volumes create kotopotok_data --region fra --size 1
   fly secrets set TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHANNEL_ID="@..." PEXELS_API_KEY="..."
   # PEXELS_API_KEY/PIXABAY_API_KEY можно не задавать, если CONTENT_MIX=cat:0,webm:100
   fly deploy
   ```
3. В `fly.toml` замени `app = "kotopotok"` на своё уникальное имя.
4. Проверь: `https://kotopotok.fly.dev/health`.

`auto_stop_machines = false` и `min_machines_running = 1` нужны, чтобы бот не засыпал.

### Вариант C. Render (проще, но free-лимиты могут меняться)

1. Создай Web Service из этого репозитория/папки.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python app.py`
4. Добавь env-переменные из `.env.example`.
5. Добавь Disk `/data` и задай `DATA_DIR=/data`.
6. Health check path: `/health`.

> Render free web services могут засыпать. Если это произойдёт — добавь внешний пинг `/health` раз в 10 минут (например, cron-job.org) или переходи на Fly/Oracle.

### Вариант D. Oracle Always Free VM (самый надёжный «бесплатный навсегда»)

Внимание: Oracle блокирует регистрацию из некоторых стран по экспортным правилам. Если видишь `unable to process your request ... Export laws` — используй Вариант A.

На Ubuntu VM:

```bash
sudo apt update && sudo apt install -y docker.io git
sudo systemctl enable --now docker
sudo mkdir -p /opt/kotopotok/data
sudo docker run -d --name kotopotok --restart unless-stopped \
  -p 8080:8080 \
  -v /opt/kotopotok/data:/data \
  -e DATA_DIR=/data \
  -e TELEGRAM_BOT_TOKEN="..." \
  -e TELEGRAM_CHANNEL_ID="@..." \
  -e PEXELS_API_KEY="..." \
  python:3.12-slim python -c "import sys; sys.path.insert(0,'/app')"
```

Для настоящего деплоя скопируй код на сервер и используй `deploy/Dockerfile`:

```bash
cd /opt/kotopotok
sudo docker build -f deploy/Dockerfile -t kotopotok .
sudo docker run -d --name kotopotok --restart unless-stopped -p 8080:8080 \
  -v /opt/kotopotok/data:/data -e DATA_DIR=/data \
  --env-file /opt/kotopotok/.env kotopotok
```

`--restart unless-stopped` — это и есть «работает сам»: после перезагрузки сервера контейнер поднимется сам.

---

## Самовосстановление

- `/health` возвращает `{"ok": true, ...}`.
- `POST_INTERVAL_MIN` и `paused` хранятся в базе, поэтому перезапуск не сбрасывает настройки.
- offset Telegram-команд тоже сохраняется — команды не теряются.
- Если API источника временно недоступен, бот пробует другой источник и следующий запрос.
- Если публикация упала, бот пишет тебе в личку (не чаще раза в час) и повторяет через 5 минут.

---

## Если в логах `WinError 10060` / `Сеть недоступна`

Это значит, что с текущего ПК **недоступен `api.telegram.org`** — бот не может получить команды и опубликовать пост. Проверить можно так:

```cmd
curl -I https://api.telegram.org
```

Решения:

1. **Включить VPN/proxy** на этом ПК и перезапустить бота. Если прокси HTTP, можно добавить в `.env`:
   ```env
   HTTPS_PROXY=http://127.0.0.1:7890
   ```
2. **DRY_RUN + MOCK_MODE** — локальная проверка без Telegram; в этом режиме ошибка не важна.
3. **Перенести бота в облако** — лучший вариант: Fly.io / Render / Oracle сами имеют доступ к Telegram API, и домашний ПК может быть выключен.

Строка `Админ не задан — напиши боту /start` — не ошибка: бот просто ждёт первой команды от админа. Но пока нет доступа к Telegram API, команда до бота не дойдёт.

---

## Структура

```text
content_bot/
  app.py              # точка входа
  bot.py              # планировщик и команды
  config.py           # .env -> Config
  net.py              # HTTP без сторонних библиотек
  sources.py          # Pexels / Pixabay / Wikimedia Commons WebM / MOCK
  publisher.py        # скачивание, caption, интервал
  telegram_api.py     # Bot API
  storage.py          # SQLite: дедупликация и состояние
  health.py           # /health, /stats
  .github/workflows/  # расписание GitHub Actions (--once)
  deploy/             # Docker, Fly, Render, Oracle, GitHub Actions
  tests/              # unittest
```

## Тесты

```powershell
python -m unittest discover -s tests -v
```
