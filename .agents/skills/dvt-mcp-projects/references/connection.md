# Подключение DVT MCP

URL MCP зависит от инсталляции DVT у заказчика: используй точный адрес, предоставленный администратором этой инсталляции. Пользователь создаёт персональный API-ключ в профиле соответствующей DVT-инсталляции, копирует его при создании, выдаёт минимально нужные права и выбирает срок действия. Ключ является секретом: не помещай его в репозиторий, сообщения, скриншоты или логи. При утечке ключ отзывают и перевыпускают.

Общий принцип для любого AI-клиента: используй предоставленный инсталляцией Streamable HTTP endpoint и bearer token из секретного хранилища или переменной окружения. Формат конфигурации и способ передачи переменной зависят от клиента. Ниже приведён пример с пользовательской переменной Windows DVT_MCP_TOKEN; имя можно выбрать другое, но оно должно совпадать в скрипте и конфигурации клиента.

## Добавление переменной в Windows

В PowerShell введи токен интерактивно, чтобы он не попал в историю команд:

```powershell
$variableName = 'DVT_MCP_TOKEN'
$secureToken = Read-Host 'Токен из DVT' -AsSecureString
$tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)
    if ([string]::IsNullOrWhiteSpace($plainToken) -or $plainToken -match '[\x00-\x1F\x7F]') {
        throw 'Ввод токена некорректен; переменная не сохранена.'
    }
    [Environment]::SetEnvironmentVariable($variableName, $plainToken, 'User')
    [Environment]::SetEnvironmentVariable($variableName, $plainToken, 'Process')
    'Токен сохранён'
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr)
    $plainToken = $null
    $secureToken = $null
}
```

Вызов SetEnvironmentVariable с областью User сохраняет значение для будущих процессов, а с областью Process — для текущего PowerShell. Не выводи значение переменной; проверяй формат ввода без раскрытия токена:

```powershell
$variableName = 'DVT_MCP_TOKEN'
$token = [Environment]::GetEnvironmentVariable($variableName, 'User')
if ($token -and -not [string]::IsNullOrWhiteSpace($token) -and $token -notmatch '[\x00-\x1F\x7F]') {
    'Токен сохранён, формат ввода корректен'
} else {
    'Токен отсутствует или ввод некорректен'
}
$token = $null
```

Не вставляй действующий токен строковым литералом в команду: она останется в истории PowerShell.

## Пример конфигурации Codex

В `%USERPROFILE%\.codex\config.toml` хранится только имя переменной:

```toml
[mcp_servers.dvt_instance]
enabled = true
url = "https://dvt.example.org/mcp"
bearer_token_env_var = "DVT_MCP_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 120
default_tools_approval_mode = "writes"
```

Это пример для Codex: замени весь URL на адрес MCP своей инсталляции и используй то же имя переменной, что в скрипте. Формат не является общим для других AI-клиентов. Не создавай вторую секцию с тем же именем. После установки переменной или изменения конфигурации полностью перезапусти клиент: уже работающий процесс не получит обновлённую пользовательскую переменную.

## Проверка и неисправности

Проверь, что клиент видит MCP-сервер и его инструменты; затем выполни read-only `search_nodes` с малым лимитом и `list_projects`. Для Codex доступны `codex mcp list` и `/mcp`. Если инструменты не появились, сначала проверь формат сохранённого токена без вывода значения, затем точный URL MCP целиком, включение сервера, переменную и перезапуск клиента. Если переменная видна в PowerShell, но не клиенту, клиент мог стартовать раньше её установки. При `401/403` проверь срок действия и права ключа без вывода значения. Timeout инициализации или вызова можно настраивать в клиенте, но timeout не доказывает остановку серверной задачи — проверь статус отдельно.
