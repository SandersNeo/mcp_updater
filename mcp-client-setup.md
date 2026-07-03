# Подключение MCP серверов в Codex и Cursor

Эта инструкция описывает подключение production MCP servers, которые уже описаны в `C:\mcp-updater-data\<project>\project.json`, к Codex и Cursor.

Генератор не меняет настройки клиентов автоматически. Он создает два файла, которые нужно перенести или объединить с текущими настройками Codex/Cursor вручную.

## Предварительные условия

- На машине с Docker есть каталог `C:\mcp-updater-data`.
- В проектных каталогах есть файлы `project.json`.
- Production MCP containers уже запущены и доступны по портам из `project.json`.
- Машина, где запускаются Codex или Cursor, видит Docker host по имени `1c-mcp`.

Если клиент запускается на той же машине, где открыт порт Docker, вместо `1c-mcp` можно использовать `localhost`.

## 1. Сгенерировать конфиги

Запустите из корня репозитория updater:

```powershell
python .\generate_mcp_client_configs.py `
  --data-root C:\mcp-updater-data `
  --output-dir C:\mcp-updater-data\client-configs `
  --client-host 1c-mcp
```

Результат:

- `C:\mcp-updater-data\client-configs\codex-mcp-servers.toml` - секции для Codex `config.toml`.
- `C:\mcp-updater-data\client-configs\cursor-mcp.json` - объект `mcpServers` для Cursor.

Если в `project.json` уже указаны URL, которые должны попасть в клиентские настройки без замены host, запустите генератор с `--no-host-override`.

## 2. Подключить в Codex

Откройте пользовательский конфиг Codex:

```text
%USERPROFILE%\.codex\config.toml
```

Добавьте в него содержимое файла:

```text
C:\mcp-updater-data\client-configs\codex-mcp-servers.toml
```

Пример секции:

```toml
[mcp_servers.1c-code-metadata-mcp-orders]
enabled = true
url = "http://1c-mcp:8100/mcp"
```

Если секция с таким же именем уже есть, замените старую секцию новой. Не оставляйте два блока `[mcp_servers.<id>]` с одинаковым именем.

После изменения `config.toml` запустите новую сессию Codex.

## 3. Подключить в Cursor

Сгенерированный файл:

```text
C:\mcp-updater-data\client-configs\cursor-mcp.json
```

имеет вид:

```json
{
  "mcpServers": {
    "1c-code-metadata-mcp-orders": {
      "url": "http://1c-mcp:8100/mcp",
      "connection_id": "1c_code_metadata_mcp_orders"
    }
  }
}
```

Для глобального подключения используйте Cursor MCP config:

```text
%USERPROFILE%\.cursor\mcp.json
```

Для подключения только в одном workspace используйте:

```text
<workspace>\.cursor\mcp.json
```

Если Cursor config еще пустой, можно использовать сгенерированный `cursor-mcp.json` как основу. Если в нем уже есть `mcpServers`, перенесите внутрь существующего объекта только новые generated entries. Не заменяйте весь файл, если там есть другие MCP servers.

После изменения config перезапустите Cursor или выполните reload MCP settings в интерфейсе Cursor.

## 4. Проверка

Проверьте, какие URL попали в сгенерированные файлы:

```powershell
Get-Content C:\mcp-updater-data\client-configs\codex-mcp-servers.toml
Get-Content C:\mcp-updater-data\client-configs\cursor-mcp.json
```

Минимальная проверка одного endpoint из updater:

```powershell
python .\mcp_smoke_test.py `
  --url http://1c-mcp:8100/mcp `
  --timeout 120 `
  --index-code `
  --metadata-query "Конфигурации" `
  --code-query "Процедура"
```

Если smoke-test проходит, endpoint доступен и MCP отвечает на tool calls. После этого проверьте, что Codex или Cursor видит server в списке подключенных MCP.

## Частые проблемы

`localhost` указывает не на ту машину: если Codex/Cursor запущены не на Docker host, используйте `--client-host 1c-mcp` или имя машины, доступное с клиентского компьютера.

Клиент не видит MCP server: проверьте DNS/hosts для `1c-mcp`, firewall и доступность порта. После правки config запустите новую сессию Codex или reload Cursor.

Есть дубли server names: удалите старую секцию Codex `[mcp_servers.<id>]` или старую запись Cursor `mcpServers.<id>`.

Endpoint отвечает медленно или нестабильно: сначала проверьте его через `mcp_smoke_test.py` и Docker logs. Не запускайте tool `reindex` из клиента вручную.

## Ссылки

- Codex config reference: https://developers.openai.com/codex/config-reference
- Cursor MCP documentation: https://cursor.com/docs/mcp
