# Подключение DVT MCP

Для dev-окружения в исходном руководстве указан `https://dvt-dev.internal.denvic.tech/mcp`; перед настройкой проверь актуальность адреса и доступ к порталу из нужной сети. Пользователь создаёт персональный API-ключ в профиле DVT (в исходном окружении — `/profile/api-keys`), копирует его при создании, выдаёт минимально нужные права и выбирает срок действия. Ключ является секретом: не помещай его в репозиторий, сообщения, скриншоты или логи. При утечке ключ отзывают и перевыпускают.

Общий принцип для любого AI-клиента: Streamable HTTP endpoint `/mcp`, bearer token из секретного хранилища или переменной окружения, клиенту только необходимые права. Формат конфигурации и способ передачи переменной зависят от клиента. В примере ниже используется пользовательская переменная Windows `DVT_DEV_MCP_TOKEN`.

## Добавление переменной в Windows

В PowerShell введи токен интерактивно, чтобы он не попал в историю команд:

```powershell
$secureToken = Read-Host 'Токен из DVT' -AsSecureString
$tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)
    [Environment]::SetEnvironmentVariable('DVT_DEV_MCP_TOKEN', $plainToken, 'User')
    $env:DVT_DEV_MCP_TOKEN = $plainToken
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr)
    $plainToken = $null
    $secureToken = $null
}
```

`SetEnvironmentVariable(..., 'User')` сохраняет значение для будущих процессов. Присваивание `$env:DVT_DEV_MCP_TOKEN` делает его доступным в текущем PowerShell. Команда `$env:DVT_DEV_MCP_TOKEN` выводит токен целиком, поэтому для проверки используй только наличие:

```powershell
if ($env:DVT_DEV_MCP_TOKEN) { 'DVT_DEV_MCP_TOKEN установлен' }
```

Не вставляй действующий токен строковым литералом в команду: она останется в истории PowerShell.

## Пример конфигурации Codex

В `%USERPROFILE%\.codex\config.toml` хранится только имя переменной:

```toml
[mcp_servers.dvt_dev_mcp]
enabled = true
url = "https://dvt-dev.internal.denvic.tech/mcp"
bearer_token_env_var = "DVT_DEV_MCP_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 120
default_tools_approval_mode = "writes"
```

Это пример для Codex, не общий формат конфигурации других AI. Не создавай вторую секцию с тем же именем. После установки переменной или изменения конфигурации полностью перезапусти клиент: уже работающий процесс не получит обновлённую пользовательскую переменную.

## Проверка и неисправности

Проверь, что клиент видит MCP-сервер и его инструменты; затем выполни read-only `search_nodes` с малым лимитом и `list_projects`. Для Codex доступны `codex mcp list` и `/mcp`. Если инструменты не появились, проверь URL с `/mcp`, включение сервера, переменную и перезапуск клиента. Если переменная видна в PowerShell, но не клиенту, клиент мог стартовать раньше её установки. При `401/403` проверь срок действия и права ключа без вывода значения. Timeout инициализации или вызова можно настраивать в клиенте, но timeout не доказывает остановку серверной задачи — проверь статус отдельно.
