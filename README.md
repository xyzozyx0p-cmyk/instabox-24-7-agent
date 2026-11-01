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
- `INSTABOX_MACHINE_ID` — ID основной машины;
- `WATCHDOG_INTERVAL_SECONDS` — интервал, по умолчанию 300;
- `API_TIMEOUT_SECONDS` — HTTP timeout, по умолчанию 20;
- `PROGRESS_MAX_AGE_SECONDS` — допустимый возраст progress heartbeat, по умолчанию 1800;
- `PROGRESS_FILE` — путь к файлу, который обновляет рабочий агент;
- `STATE_DIR` — каталог состояния и event log.

## Локальный запуск

```bash
cp .env.example .env
# заполните .env
python3 watchdog/main.py
```

## Следующий этап

После получения ID машины и подтверждения тарифа можно подключить Render service, secrets, alerting и реальную стратегию checkpoints. Запуск Claude Code намеренно не включён в этот первый безопасный этап.
