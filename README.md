# Instabox 24/7 Agent Watchdog

Безопасный первый этап проекта: watchdog для основной машины InstaBox. Он проверяет состояние через официальный API, будит paused-машину через `resume`, ведёт журнал событий и отдельно проверяет прогресс агента.

## Что входит

- Python watchdog без внешних зависимостей;
- официальный InstaBox API `https://api.instabox.sh`;
- идемпотентные lifecycle-запросы;
- разделение `liveness`, `anti_sleep` и `progress`;
- Render Blueprint для платного постоянного worker/service;
- systemd unit для постоянного третьего сервера;
- checkpoints через локальный каталог, который затем можно подключить к внешнему объектному хранилищу.

## Важные ограничения

На бесплатном плане InstaBox auto-pause фиксирован на 30 минут и не отключается. На платном плане его можно отключить штатной настройкой. Этот watchdog не имитирует действия пользователя и не обходить ограничения платформы: он использует официальный API.

Не добавляйте API-ключи в Git. Перед запуском скопируйте `.env.example` в `.env` и задайте переменные в Render Secrets или systemd EnvironmentFile.

## Переменные окружения

- `INSTABOX_API_KEY` — API key с минимальными scope;
- `INSTABOX_MACHINE_NAME` — имя основной машины из dashboard; Instabox API принимает имя в URL так же, как внутренний ID;
- `INSTABOX_MACHINE_ID` — внутренний ID машины, необязательный альтернативный вариант;
- `WATCHDOG_INTERVAL_SECONDS` — интервал, по умолчанию 300;
- `API_TIMEOUT_SECONDS` — HTTP timeout, по умолчанию 20;
- `PROGRESS_MAX_AGE_SECONDS` — допустимый возраст progress heartbeat, по умолчанию 1800;
- `PROGRESS_FILE` — путь к файлу, который обновляет рабочий агент;
- `STATE_DIR` — каталог состояния и event log;
- `ALLOW_DESTRUCTIVE_ACTIONS` — должен быть `true` только для ручных `stop`, `suspend` или `restart`;
- `CONTROL_WAIT_SECONDS` — сколько ждать завершения stop перед restart.

## Локальный запуск

```bash
cp .env.example .env
# заполните .env
python3 watchdog/main.py
```

Одноразовые lifecycle-команды используют тот же API-ключ и ID машины:

```bash
python3 watchdog/main.py resume   # разбудить paused-машину
python3 watchdog/main.py start    # запустить stopped-машину
python3 watchdog/main.py stop     # только при ALLOW_DESTRUCTIVE_ACTIONS=true
python3 watchdog/main.py suspend  # только при ALLOW_DESTRUCTIVE_ACTIONS=true
python3 watchdog/main.py restart  # stop -> ожидание -> start, только явно разрешённая операция
```

На бесплатном плане API позволяет выполнять lifecycle-операции, но `auto-pause` остаётся фиксированным на 30 мин. Нельзя отключить его через API. Поэтому `monitor` периодически проверяет состояние и вызывает `resume`, если машина уснула.

## Следующий этап

После получения имени машины и подтверждения тарифа можно подключить Render service, secrets, alerting и реальную стратегию checkpoints. Запуск Claude Code намеренно не включён в этот первый безопасный этап.
