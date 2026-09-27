# INDIV Bitrix24 MCP

MCP-прокси между ChatGPT/Claude и REST webhook Bitrix24.

Инструменты: `list_deals`, `get_deal`, `update_deal`, `list_companies`, `get_company`, `list_contacts`, `get_contact`, `list_deal_categories`, `list_deal_stages`, `count_deals_by_stage`, `list_disk_storages`, `list_disk_storage_children`, `list_disk_folder_children`, `get_disk_file`.

## Переменные окружения

```text
BITRIX_BASE=https://YOUR_PORTAL.bitrix24.ru/rest/USER_ID/WEBHOOK_SECRET/
MCP_TOKEN=long-random-secret
PORT=3000
```

`BITRIX_BASE` должен заканчиваться `/` и не должен содержать имя REST-метода.

После развёртывания endpoint:

```text
https://YOUR-HOST/mcp/YOUR_MCP_TOKEN
```

Webhook должен иметь права CRM и, для файлов, Диск. Никогда не коммитьте настоящий webhook или `MCP_TOKEN` в GitHub.
