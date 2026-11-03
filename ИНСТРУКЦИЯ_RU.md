# Инструкция: SSH, Claude Code и Control API

Эта инструкция описывает подключение к основной Instabox-машине, получение токена, вход в веб-интерфейс, отправку сообщений Claude Code, просмотр вывода и подключение к терминалу в реальном времени.

## 1. Данные подключения

Публичный адрес API:

```text
https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech
```

Страница входа:

```text
https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/
```

Документация Swagger:

```text
https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/docs
```

Временный SSH-доступ:

```bash
ssh -p 2222 ibssh_denpzef4tpwbmtnfhtcshtidzm@ssh.instabox.sh
```

Имя пользователя и SSH-ключ являются временными. Если доступ перестанет работать, нужно создать новую временную SSH-команду в Instabox.

## 2. Откуда взять API-токен

Токен был автоматически создан при установке Control API и сохранён только на основной машине в файле:

```text
/data/infra/control-plane/api.env
```

Получить токен можно через SSH:

```bash
ssh -p 2222 ibssh_denpzef4tpwbmtnfhtcshtidzm@ssh.instabox.sh \
  'grep CONTROL_API_TOKEN /data/infra/control-plane/api.env'
```

Команда выведет строку вида:

```text
CONTROL_API_TOKEN=длинная_секретная_строка
```

Для веб-входа нужно скопировать только значение после `CONTROL_API_TOKEN=`.

Токен нельзя отправлять в чат, публиковать в GitHub или вставлять в URL.

## 3. Вход через сайт

1. Откройте:

   ```text
   https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/
   ```

2. Вставьте значение `CONTROL_API_TOKEN`.
3. Нажмите **Войти**.
4. При успешной проверке браузер получит защищённую HttpOnly-cookie.
5. После этого можно открыть Swagger:

   ```text
   https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/docs
   ```

Кнопка **Authorize** в Swagger сама по себе не проверяет токен. Она только сохраняет строку в интерфейсе. Настоящая проверка происходит при выполнении запроса сервером. Неправильный токен получает `401 Unauthorized`.

## 4. Подготовка команд API

В Linux, macOS или Git Bash:

```bash
export API_URL="https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech"
export TOKEN="вставьте_сюда_значение_CONTROL_API_TOKEN"
```

В Windows PowerShell:

```powershell
$env:API_URL = "https://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech"
$env:TOKEN = "вставьте_сюда_значение_CONTROL_API_TOKEN"
```

Не добавляйте токен в Git, скрипты общего доступа или URL.

## 5. Проверка статуса

```bash
curl "$API_URL/v1/status" \
  -H "Authorization: Bearer $TOKEN"
```

Пример ответа:

```json
{
  "ok": true,
  "workspace": "/data/workspace",
  "default_project": "/data/workspace/instabox-24-7-agent",
  "sessions": ["claude", "terminal-main"],
  "claude_installed": true
}
```

Проверка доступности сервиса без авторизации:

```bash
curl "$API_URL/healthz"
```

`/healthz` показывает только, что API работает. Для управления всегда нужен токен.

## Передача файлов через API

Файлы можно загружать и скачивать в любом формате: ZIP, PDF, DOCX, XLSX, изображения, видео, исходный код и другие типы.

Для безопасности API разрешает операции только внутри:

```text
/data/workspace
```

Нельзя через API прочитать или перезаписать системные файлы за пределами workspace. Пути с `..` также отклоняются.

### Список файлов

Список корня workspace:

```bash
curl "$API_URL/v1/files?path=" \
  -H "Authorization: Bearer $TOKEN"
```

Список конкретного проекта:

```bash
curl "$API_URL/v1/files?path=instabox-24-7-agent" \
  -H "Authorization: Bearer $TOKEN"
```

### Загрузка файла на сервер

```bash
curl -X POST "$API_URL/v1/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F path=instabox-24-7-agent/input.zip \
  -F file=@./input.zip
```

Пример загрузки изображения:

```bash
curl -X POST "$API_URL/v1/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F path=instabox-24-7-agent/assets/photo.png \
  -F file=@./photo.png
```

Каталоги создаются автоматически. Если файл с таким путём уже существует, он будет заменён.

### Скачивание файла с сервера

```bash
curl "$API_URL/v1/files/download?path=instabox-24-7-agent/output.zip" \
  -H "Authorization: Bearer $TOKEN" \
  -o output.zip
```

Все файловые запросы требуют тот же Bearer-токен, что и управление Claude.

## 6. Запуск Claude Code

Запустить persistent-сессию Claude:

```bash
curl -X POST "$API_URL/v1/claude/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"claude"}'
```

Persistent-сессия продолжает работать после закрытия браузера или разрыва SSH.

## 7. Отправка сообщения Claude

```bash
curl -X POST "$API_URL/v1/claude/message" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"claude","message":"Проверь состояние проекта и опиши текущую задачу"}'
```

Для сообщений с кавычками и переносами строк удобнее использовать Python или файл JSON. Пример через Python:

```bash
python3 - <<'PY'
import json, os, urllib.request

url = os.environ["API_URL"] + "/v1/claude/message"
data = json.dumps({
    "session": "claude",
    "message": "Проверь git status, последние ошибки и предложи план исправления"
}).encode()
request = urllib.request.Request(
    url,
    data=data,
    method="POST",
    headers={
        "Authorization": "Bearer " + os.environ["TOKEN"],
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request) as response:
    print(response.read().decode())
PY
```

## 8. Получение вывода Claude

```bash
curl "$API_URL/v1/claude/output?session=claude&lines=200" \
  -H "Authorization: Bearer $TOKEN"
```

Параметр `lines` определяет количество последних строк терминала.

## 9. Выполнение команды в сессии

Команда отправляется в указанную tmux-сессию и выполняется так же, как команда в SSH-терминале:

```bash
curl -X POST "$API_URL/v1/command" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"terminal-main","command":"pwd && git status"}'
```

Для команды в Claude-сессии:

```bash
curl -X POST "$API_URL/v1/command" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"claude","command":"покажи последние ошибки"}'
```

API намеренно предоставляет SSH-подобный доступ. Любой, у кого есть токен, сможет выполнять команды в разрешённых каталогах. Поэтому токен нужно защищать как пароль.

## 10. Создание отдельного терминала

```bash
curl -X POST "$API_URL/v1/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"terminal-2"}'
```

После этого появится persistent tmux-сессия `terminal-2`.

Допустимые имена сессий состоят из латинских букв, цифр, `_` и `-`.

## 11. Терминал в реальном времени через WebSocket

Адрес терминала Claude:

```text
wss://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/v1/sessions/claude/ws
```

Адрес терминала `terminal-main`:

```text
wss://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/v1/sessions/terminal-main/ws
```

После подключения первым текстовым сообщением нужно отправить:

```json
{"token":"ваш_CONTROL_API_TOKEN"}
```

Затем WebSocket передаёт двоичные данные терминала в обе стороны:

- данные от сервера — вывод терминала и Claude;
- данные от клиента — нажатия клавиш и команды;
- поддерживаются Ctrl+C, Enter и другие управляющие клавиши.

Пример клиента на Python:

```bash
pip install websocket-client
```

```python
import json
import os
import ssl
import websocket

url = "wss://8787-agqzewoscn6joxoco3pyeudmqm.instabox.tech/v1/sessions/claude/ws"
ws = websocket.create_connection(url, timeout=30)
ws.send(json.dumps({"token": os.environ["TOKEN"]}))

try:
    while True:
        data = ws.recv()
        if isinstance(data, bytes):
            print(data.decode(errors="replace"), end="")
        else:
            print(data, end="")
except KeyboardInterrupt:
    ws.close()
```

Для полноценного терминального интерфейса программа-клиент должна передавать на WebSocket нажатия клавиш и отображать полученные байты.

## 12. Подключение напрямую через SSH-туннель

Если публичный адрес временно недоступен, API можно использовать через SSH port forwarding:

```bash
ssh -p 2222 \
  -L 8787:127.0.0.1:8787 \
  ibssh_denpzef4tpwbmtnfhtcshtidzm@ssh.instabox.sh
```

После этого в другом окне терминала:

```bash
export API_URL="http://127.0.0.1:8787"
curl "$API_URL/healthz"
```

## 13. Перезапуск API

Если API перестал отвечать, войдите по SSH и выполните:

```bash
sudo systemctl restart claude-control-plane.service
sudo systemctl status claude-control-plane.service
```

Посмотреть логи:

```bash
sudo journalctl -u claude-control-plane.service -n 100 --no-pager
```

Проверить локальный health endpoint:

```bash
curl http://127.0.0.1:8787/healthz
```

## 14. Смена токена

Если токен стал известен посторонним, создайте новый:

```bash
ssh -p 2222 ibssh_denpzef4tpwbmtnfhtcshtidzm@ssh.instabox.sh
```

На сервере:

```bash
cd /data/infra/control-plane
NEW_TOKEN=$(openssl rand -hex 32)
printf 'CONTROL_API_TOKEN=%s\nCONTROL_WORKSPACE=/data/workspace\nCONTROL_PROJECT=/data/workspace/instabox-24-7-agent\nCONTROL_PORT=8787\n' "$NEW_TOKEN" > api.env
chmod 600 api.env
sudo chown user:user api.env
sudo systemctl restart claude-control-plane.service
echo "$NEW_TOKEN"
```

После смены старый токен перестанет работать. Новый токен нужно хранить только у себя.

## 15. Безопасность

- Не передавайте токен в чат.
- Не вставляйте токен в URL.
- Не публикуйте `api.env` в GitHub.
- Не оставляйте токен в shell history, если компьютер общий.
- При подозрении на утечку сразу смените токен.
- Не запускайте неизвестные команды, полученные от непроверенных источников.
- Порт API не должен быть доступен без авторизации.
- Для постоянной публичной работы желательно дополнительно включить Cloudflare Access или ограничение по IP.

## 16. Исходный код

Репозиторий проекта:

```text
https://github.com/xyzozyx0p-cmyk/instabox-24-7-agent
```

Основные файлы:

- `control-plane/control_plane.py` — API и WebSocket terminal bridge;
- `control-plane/claude-control-plane.service` — systemd-сервис;
- `watchdog/main.py` — Render watchdog и автоматический resume/start основной машины;
- `cloudflare-worker/worker.js` — периодический контроль Render и Instabox.
