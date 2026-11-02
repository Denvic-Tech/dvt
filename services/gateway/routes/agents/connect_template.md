# Подключение AI-агента к DVT {{DVT_HOST}}

Это инструкция для AI-агента (Claude Code, Codex, Cursor, Gemini CLI и других). Если ты агент,
выполни её по шагам. Если ты человек, просто отправь ссылку на этот документ своему агенту.

## Что подключаем

- DVT: {{DVT_URL}}
- MCP-сервер DVT: `{{DVT_MCP_URL}}`, транспорт Streamable HTTP
- Авторизация: заголовок `Authorization: Bearer <MCP-токен>`

Токен не нужно спрашивать у пользователя. Ссылка на этот документ содержит одноразовый код,
и DVT выдаёт токен по адресу `{{CLAIM_URL}}` ровно один раз, в течение 10 минут после создания
ссылки. Токен должен попасть из ответа DVT напрямую в настройки клиента: получай его только
подстановкой внутри команды, как показано ниже, никогда не выводи его на экран, не сохраняй в
переменные сессии и не вставляй в файлы через свои инструменты редактирования. Если обмен вернул
ошибку 404 или 410, код устарел или уже использован: попроси пользователя создать новую ссылку
в DVT и остановись.

## Шаг 1. Определи, в каком клиенте ты работаешь

Определи по своему окружению и инструментам, какой из разделов ниже твой. Если не уверен,
спроси пользователя: «Я работаю в Claude Code, Codex, Cursor или другом приложении?»

## Шаг 2. Подключи MCP-сервер

### Claude Code (терминал, VS Code, десктоп-приложение Claude, вкладка Code)

В bash или zsh:

```
claude mcp add --transport http --scope user dvt "{{DVT_MCP_URL}}" --header "Authorization: Bearer $(curl -sf {{CLAIM_URL}})"
```

В PowerShell:

```
claude mcp add --transport http --scope user dvt "{{DVT_MCP_URL}}" --header "Authorization: Bearer $(Invoke-RestMethod '{{CLAIM_URL}}')"
```

Если команда `claude` недоступна, выполни ту же подстановку скриптом оболочки, который дописывает
сервер `dvt` в объект `mcpServers` файла `~/.claude.json` (на Windows `%USERPROFILE%\.claude.json`),
не меняя остальное содержимое:

```json
"dvt": { "type": "http", "url": "{{DVT_MCP_URL}}", "headers": { "Authorization": "Bearer <токен из обмена>" } }
```

Проверка: `claude mcp list` должен показать `dvt … ✔ Connected`. Не используй `claude mcp get`:
он печатает заголовки вместе с токеном.

### Codex (CLI и приложение)

Токен хранится в `~/.codex/config.toml` как статический заголовок сервера. Не используй
переменные окружения и `setx`: песочница Codex запрещает запись в реестр Windows. Сначала
зарегистрируй сервер:

```
codex mcp add dvt --url "{{DVT_MCP_URL}}"
```

Затем одной командой добавь заголовок в секцию `[mcp_servers.dvt]` файла `~/.codex/config.toml`.

В PowerShell:

```
$p = Join-Path $HOME '.codex\config.toml'; $raw = [IO.File]::ReadAllText($p); $new = [regex]::Replace($raw, '(?m)^(\[mcp_servers\.dvt\]\r?\n)', ('$1http_headers = { Authorization = "Bearer ' + (Invoke-RestMethod '{{CLAIM_URL}}') + '" }' + "`n"), 1); [IO.File]::WriteAllText($p, $new, (New-Object Text.UTF8Encoding($false)))
```

В bash или zsh:

```
perl -0pi -e 's/^(\[mcp_servers\.dvt\]\n)/$1http_headers = { Authorization = "Bearer '"$(curl -sf {{CLAIM_URL}})"'" }\n/m' ~/.codex/config.toml
```

Проверка: `codex mcp list` показывает `dvt` со статусом `enabled` и `Auth: Bearer token`.
Не используй `codex mcp get dvt`: он печатает заголовки вместе с токеном. Конфигурация читается
при запуске, поэтому Codex нужно перезапустить.

### Cursor

Одной командой оболочки добавь в `~/.cursor/mcp.json` (создай файл, если его нет) в объект
`mcpServers` запись, подставив токен из `{{CLAIM_URL}}` внутри команды:

```json
"dvt": { "url": "{{DVT_MCP_URL}}", "headers": { "Authorization": "Bearer <токен из обмена>" } }
```

### VS Code (Copilot)

```
code --add-mcp "{\"name\":\"dvt\",\"type\":\"http\",\"url\":\"{{DVT_MCP_URL}}\",\"headers\":{\"Authorization\":\"Bearer $(curl -sf {{CLAIM_URL}})\"}}"
```

### Gemini CLI

```
gemini mcp add --transport http --scope user dvt "{{DVT_MCP_URL}}" --header "Authorization: Bearer $(curl -sf {{CLAIM_URL}})"
```

### Другой клиент

Добавь удалённый MCP-сервер с адресом `{{DVT_MCP_URL}}` и заголовком
`Authorization: Bearer <токен>` тем способом, который поддерживает клиент, получив токен
подстановкой из `{{CLAIM_URL}}` внутри команды.

Если клиент запретил запись (песочница, права), попроси у пользователя разрешение на эту
операцию или скажи, какую команду выполнить ему самому. Не проси токен в чат: повторный запрос
по тому же адресу обмена в течение 10 минут вернёт новый действующий токен.

## Шаг 3. Заверши

1. Скажи пользователю открыть новый чат: MCP-серверы подключаются при старте сессии.
2. В новом чате попроси его проверить подключение: любой инструмент DVT только для чтения,
   например список проектов.
3. Если DVT ответил 401 или 403, токен отозван: пользователю нужно создать новую ссылку.
   Если соединения нет, проверить адрес и VPN.
