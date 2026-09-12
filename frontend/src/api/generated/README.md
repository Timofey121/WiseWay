# Generated API-артефакты

Содержимое этого каталога генерируется из единственного публичного контракта
`contracts/openapi/wiseway-v1.yaml` (OpenAPI 3.1.1, `info.version: 1.0.0`) и не
редактируется вручную.

| Файл | Что это | Как получить |
|---|---|---|
| `schema.ts` | TypeScript-типы всех 33 операций и схем (`openapi-typescript` 7) | `npm run generate:api` |
| `openapi.json` | Тот же OAS, сконвертированный YAML → JSON для runtime-mocks (WP-06/WP-07); браузеру не нужен YAML-парсер | `npm run generate:api` |
| `operation-meta.ts` | Карта `METHOD path` → `{ operationId, csrf, idempotencyKey }` для транспорта; `csrf`/`idempotencyKey` выведены из наличия `$ref` на `#/components/parameters/XCSRFToken` и `#/components/parameters/IdempotencyKey` | `npm run generate:api` |
| `client.ts` | Типизированная фабрика клиента на `openapi-fetch` поверх `schema.ts` (пишется вручную, схемы не дублирует) | — |
| `README.md` | Этот файл | — |

Команда генерации воспроизводима: повторный запуск при неизменном OAS не
изменяет `schema.ts`, `openapi.json` и `operation-meta.ts`. Проверка:

```powershell
npm run generate:api
git diff --exit-code -- src/api/generated
```

Дополнительная автоматическая проверка без Git:

```powershell
npm run generate:api:check
```

Не редактируйте `schema.ts`, `openapi.json` и `operation-meta.ts` вручную:
изменения будут перезаписаны следующей генерацией.
