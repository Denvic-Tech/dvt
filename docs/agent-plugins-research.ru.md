# Подключение DVT MCP к агентским платформам: исследование и предлагаемое решение

Дата: 2026-10-28. Источники: официальная документация Claude Code, Claude Desktop/claude.ai, OpenAI Codex/ChatGPT plugins, Cursor, VS Code, Gemini CLI, спецификации MCP, MCPB и Agent Plugins, плюс проверка локально установленных CLI (Claude Code 2.1.311, Codex CLI 0.149.1).

Пометки: **[док]** — подтверждено документацией, **[лок]** — проверено на этой машине, **[не проверено]** — гипотеза, нужен тест.

## 1. Задача

Вход у всех клиентов одинаковый: адрес `http(s)://<dvt>/mcp` и персональный bearer-токен из профиля DVT (`POST /api/mcp-tokens`, показывается один раз). Особенности DVT: инстансы часто доступны только по VPN и только по `http://`. Пользователь — не разработчик, чаще всего Windows + Claude Desktop.

Проблема не в том, что «нет способа», а в том, что у каждого клиента свой способ, пользователь должен сам найти нужный, достать адрес, создать токен и донести его до правильного места.

## 2. Что умеет каждая платформа (октябрь 2026)

| Клиент | Нативный способ подключить HTTP MCP с bearer | Есть форма для секрета? | Где хранится секрет | Работает с intranet `http://`? |
|---|---|---|---|---|
| Claude Code (терминал, расширение VS Code) | `claude mcp add --transport http -H "Authorization: Bearer …"`; плагин с `userConfig` (`sensitive: true`) **[док][лок]** | Да: диалог в `/plugin` при установке/включении, форма в VS Code **[док]**; из shell `claude plugin install --config key=value` **[лок]** | «secure storage»; на Windows фактически `~/.claude/.credentials.json` (plaintext) **[лок, 27.10]** | Да: статический заголовок по http допустим, запрещён только OAuth по http **[док]** |
| Claude Desktop, вкладка Code | Браузер плагинов (`+ → Add plugins`), **без** диалога `userConfig` **[лок, 27.10]**; читает те же файлы настроек, что терминал **[док]**; серверы из `claude_desktop_config.json` тоже попадают в Code-сессии **[док]** | Нет | — | Да |
| Claude Desktop, чат | (a) Custom connector по URL: запросы идут **через серверы Anthropic**, нужен публичный HTTPS; заголовки с API-ключом — закрытая бета **[док]**. (b) Desktop extension `.mcpb`: локальный stdio-сервер, Node.js **встроен** в Claude Desktop, установка двойным кликом, форма `user_config` генерируется автоматически **[док]** | (a) частично; (b) **да**, поля `sensitive` | (b) Credential Manager / Keychain **[док]** | (a) нет; (b) да |
| Codex (CLI и приложение ChatGPT/Codex) | `codex mcp add dvt --url … --bearer-token-env-var DVT_MCP_TOKEN` **[лок]**; `config.toml`: `url`, `bearer_token_env_var`, `http_headers`, `env_http_headers` **[док]**; в приложении Settings → MCP servers → Add server **[док]** | Форма в приложении есть, но токен берётся из переменной окружения | Переменная окружения (plaintext) | Да |
| Codex-плагины | Формат Agent Plugins: `plugin.json` + `mcp.json` (`streamable-http`) + `extensions.com.openai.auth = {type: api_key, headerScheme: bearer}` **[док]**; маркетплейс: `codex plugin marketplace add owner/repo` **[лок]** | Токен «вводится при connection setup» в ChatGPT **[док]**; в Codex CLI приглашения ввести ключ при установке нет (Appwrite из-за этого не бандлит свой сервер) **[не проверено для Codex-app]** | ? | URL в `mcp.json` фиксированный, per-инстанс URL задать нельзя |
| Cursor | `mcp.json` с `url` + `headers`, `${env:VAR}`; deeplink `cursor://anysphere.cursor-deeplink/mcp/install?name=…&config=<base64 json>` — один клик **[док]** | Диалог подтверждения; секрет едет внутри ссылки | `mcp.json` (plaintext) | Да |
| VS Code (Copilot) | `code --add-mcp '{json}'`; ссылка `vscode:mcp/install?<urlencoded json>`; `inputs` с `promptString` + `password: true` — VS Code сам спросит токен и сохранит в secret storage **[док]** | Да | Secret storage | Да |
| Gemini CLI | Расширение: `mcpServers.httpUrl` + `headers`, `settings[]` с `sensitive: true` → keychain, спрашивает при `gemini extensions install` **[док]** | Да (CLI) | Keychain | Да |

Что **не** подходит и почему:

- **Custom connectors claude.ai / Claude Desktop** — соединение устанавливают серверы Anthropic, поэтому DVT за VPN недостижим; заголовки с ключом только в закрытой бете. Подходит лишь для публичных HTTPS-инстансов DVT.
- **MCP tunnels** — только Enterprise, research preview, своя инфраструктура (cloudflared + proxy).
- **OAuth** — Claude Code отказывается слать credentials на `http://` token endpoint (кроме loopback).
- **MCP elicitation как «форма настройки»** — спецификация запрещает запрашивать секреты через form-mode; Claude Desktop elicitation не поддерживает вовсе.
- **Agent Plugins `mcp.json`** — стандарт прямо запрещает credentials в `headers` и не имеет механизма пользовательских значений, т.е. единый кросс-платформенный плагин сам по себе проблему токена не решает.

## 3. Ключевой вывод

Единого механизма «одна кнопка для всех» в экосистеме нет и не предвидится. Но у каждого клиента есть ровно один *нативный* путь, где секрет вводится в форму или одной командой. Все эти пути требуют двух одинаковых значений — URL и токен — и оба значения знает **сам DVT**.

Поэтому «блондинко-совместимое» решение — не плагин сам по себе, а **DVT как установщик**: страница в DVT «Подключить ИИ-агента», которая создаёт токен и для выбранного клиента отдаёт готовый артефакт с уже подставленным адресом. Репозиторий плагинов при этом остаётся — как слой контента (скиллы, мост, шаблоны) и как публичный маркетплейс для тех, кто ставит вручную.

## 4. Предлагаемая архитектура

### 4.1 Репозиторий `dvt-agent-plugins` (публичный GitHub, слой контента)

```
dvt-agent-plugins/
├── .claude-plugin/marketplace.json      # маркетплейс Claude Code (и legacy-совместимый для Codex)
├── .agents/plugins/marketplace.json     # маркетплейс Codex
├── plugins/dvt/                         # один плагин в двух раскладках
│   ├── .claude-plugin/plugin.json       #   Claude Code: userConfig {mcp_url, mcp_token(sensitive)}
│   ├── .mcp.json                        #   Claude Code: http, url=${user_config.mcp_url}, Bearer ${user_config.mcp_token}
│   ├── plugin.json                      #   Agent Plugins / Codex
│   ├── mcp.json                         #   Codex: streamable-http + auth api_key/bearer
│   └── skills/                          #   dvt-mcp-projects (синхронизируется из DVT CI), setup, use
├── bridge/                              # Node: stdio ↔ Streamable HTTP с Authorization, без зависимостей кроме MCP SDK
├── mcpb/                                # manifest.json шаблон + сборка dvt.mcpb (GitHub Releases)
└── templates/                           # шаблоны артефактов, которые генерирует DVT (см. 4.2)
```

Содержимое скилла `dvt-mcp-projects` живёт в репозитории DVT (`.agents/skills/…`) и копируется в плагин CI-джобой, чтобы не расходиться.

### 4.2 DVT: страница «Подключить ИИ-агента» (слой установки)

Рядом с управлением MCP-токенами. Пользователь выбирает клиента, DVT создаёт токен с нужным scope и показывает одну кнопку/команду:

| Клиент | Что отдаёт DVT | Действия пользователя |
|---|---|---|
| **Claude Desktop** (чат; возможно и Code — см. тест T1) | `GET /agents/claude-desktop/dvt.mcpb` — бандл с мостом, в `user_config.dvt_url.default` подставлен адрес инстанса; поле `token` — `sensitive`, `required` | Скачать → двойной клик → вставить токен в форму → Install. Токен уходит в Credential Manager. Ни одного файла руками. |
| **Claude Code** (терминал, VS Code, Code-вкладка) | `GET /agents/claude/marketplace.json` — хостовый маркетплейс, в котором запись плагина **сама является манифестом** (плагин без `plugin.json` — только `skills/` с GitHub), с `mcpServers.dvt.url = <адрес инстанса>` и `userConfig.mcp_token`. Команда: `claude plugin install dvt --marketplace https://<dvt>/agents/claude/marketplace.json` **[док: entry-as-manifest, --marketplace]** | Вставить команду в терминал; Claude Code сам спросит токен в диалоге (терминал/VS Code). Для Code-вкладки desktop-приложения — `/dvt:setup` (см. 4.3). |
| **Codex** | Команда `codex mcp add dvt --url <адрес> --bearer-token-env-var DVT_MCP_TOKEN` + установка переменной; плюс `codex plugin marketplace add Denvic-Tech/dvt-agent-plugins` для скиллов | Вставить команду. Хранение в env-переменной — так устроен сам Codex. |
| **Cursor** | Кнопка «Add to Cursor» (deeplink с `url` + `headers`) | Один клик, подтвердить. |
| **VS Code** | Ссылка `vscode:mcp/install?…` с `inputs` (password) | Клик, вставить токен в приглашение VS Code. |

Сторона DVT: 2 GET-эндпоинта в Gateway (генерация `.mcpb` = zip из шаблона + `manifest.json`; генерация `marketplace.json`), одна страница в UI (сабмодуль `dvt-ui`). Адрес берётся из `DVT_PUBLIC_URL`.

### 4.3 Claude Desktop → вкладка Code (самый массовый случай)

**Проверено 28.10 (T1):** `.mcpb`-расширение, установленное в чате Claude Desktop, видно в `/mcp` локальной Code-сессии. Один `.mcpb` закрывает и чат, и Code, отдельный путь настройки для вкладки Code на Windows/macOS не нужен. Плагин `dvt` с `userConfig` остаётся для терминала и VS Code (там диалог есть); для десктоп-приложения он даёт скиллы, а MCP приходит из расширения.

### 4.4 Фаза 3: pairing-code вместо токена в командах и ссылках

Команды для Claude Code/Codex и deeplink Cursor несут токен открытым текстом (история shell, ссылка). Решение по образцу device flow: DVT выдаёт одноразовый код на 10 минут, артефакт содержит код, а не токен; мост/`headersHelper` при первом запуске меняет код на токен (`POST /api/mcp-tokens/claim`) и кладёт его в Credential Manager. Утечка кода после обмена безвредна. Это улучшение, не блокер для v1.

## 5. Фаза 0: результаты (28.10.2026)

| # | Результат |
|---|---|
| T1 | ✅ `.mcpb` из чата Claude Desktop виден во вкладке Code |
| T2 | ✅ Мост работает, форма с адресом и токеном показана, сборка `mcpb pack` проходит |
| T3 | ✅ Из shell: хостовый `marketplace.json` с записью-манифестом (адрес инстанса внутри) ставится одной командой, `plugin:dvt:dvt` подключён; токен на Windows лежит в `~/.claude/.credentials.json` (`pluginSecrets`) |
| T4 | ❌ Приложение Codex не предлагает ввести токен для плагинного сервера с `auth api_key`; для Codex — `codex mcp add --url … --bearer-token-env-var`, плагин только для скиллов |
| T5 | не проверен: на тестовой машине нет Cursor, VS Code 1.83 без MCP |

Исходный план тестов ниже сохранён для истории.

### Что нужно проверить руками до начала разработки (фаза 0)

| # | Тест | Зачем |
|---|---|---|
| T1 | Поставить тестовый `.mcpb` в Claude Desktop (Windows) и посмотреть, видны ли его инструменты в сессии Code-вкладки | Определяет, нужен ли отдельный путь для Code (4.3) |
| T2 | Мост по `http://` к локальному DVT из Claude Desktop, поле `token` → проверить запись в Credential Manager | Базовая работоспособность главного артефакта |
| T3 | `claude plugin install dvt --marketplace <https-url marketplace.json>` с entry-as-manifest (без `plugin.json`) в терминале → появляется ли диалог токена, подхватывается ли `url` из записи | Основа пути Claude Code |
| T4 | Codex-app: установка плагина с `auth api_key/bearer` из локального маркетплейса — спрашивает ли приложение токен | Решает, нужна ли Codex команда `codex mcp add` или достаточно плагина |
| T5 | Cursor deeplink с `headers`; VS Code ссылка с `inputs` | Подтвердить one-click для IDE |

Все тесты выполнимы на этой машине (установлены Claude Desktop, Claude Code 2.1.311, Codex 0.149.1, Node 22), кроме кликов в GUI, которые делает пользователь.

## 6. План работ

1. **Фаза 0 (1 день):** тесты T1–T5, фиксация результатов в README репозитория.
2. **Фаза 1 (репозиторий):** мост + `.mcpb` (релиз на GitHub), плагин `dvt` в двух раскладках, маркетплейсы, CI (`claude plugin validate`, `mcpb pack`, синхронизация скилла из DVT), README с ручными сценариями для каждого клиента.
3. **Фаза 2 (DVT):** эндпоинты генерации `marketplace.json` и `.mcpb`, страница «Подключить ИИ-агента», кнопки/команды по клиентам.
4. **Фаза 3:** pairing-code; при появлении у Anthropic/OpenAI новых нативных механизмов (headers в custom connectors вне беты, prompt секретов в Codex) — переключать соответствующие карточки на них.

## 7. Открытые риски

- На Windows «secure storage» Claude Code для `sensitive` userConfig — plaintext-файл; для Code-вкладки это приемлемо не хуже, чем `.claude.json`, но стоит сказать в документации.
- Anthropic закрыла каталог для новых `.mcpb`, но приватная раздача и установка файла остаются поддержанными; рекомендованный путь для каталога — плагины, что мы и делаем параллельно.
- Codex-плагин не умеет per-инстансный URL; для Codex мы опираемся на `codex mcp add`, плагин даёт только скиллы.
- Формат ссылки VS Code с `inputs` официально не описан — проверить T5, иначе отдавать `code --add-mcp` с токеном.
