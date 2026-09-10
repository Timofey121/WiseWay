# E-01 — отчёт о передаче по контракту

Файл фиксирует handoff контрактных leaf Epic E-01 по правилам FE §7: задача и покрытые
требования, изменённые файлы, версии контракта, что именно проверено, точные команды и
результаты, ограничения и следующий владелец. «Готово» без evidence здесь не используется.

## LT-01.1 — обязательный query-параметр `company_id` для двух GET-списков

### Задача и покрытые требования

- **Leaf:** LT-01.1 (WP-01, Epic E-01). **Status на момент handoff:** IN_PROGRESS.
- **Дефект:** B-01 — `listSortingBatches` и `listQuarantineItems` ссылались на параметр
  `CompanyId` с `in: path`, но пути `/sorting/batches` и `/quarantine` не содержат
  `{company_id}`. Это делало параметр несогласованным с путём.
- **Основание:** решение пользователя D-04 (точечные исправления допустимы без повторного
  вопроса); API §8 (GET `/sorting/batches` — `company_id, cursor?, limit?`) и API §9
  (GET `/quarantine` — `company_id, cursor?, limit?`).
- **Бизнес-семантика не изменена:** `company_id` остаётся обязательным входным
  идентификатором компании; меняется только его размещение (query вместо path) для двух
  операций, где путь его не содержит.

### Изменённые файлы

| Файл | Характер изменения |
|---|---|
| `contracts/openapi/wiseway-v1.yaml` | добавлен переиспользуемый query-параметр `CompanyIdQuery`; две GET-операции переведены на него |
| `docs/team/E-01_CONTRACT_HANDOFF.md` | этот handoff (новый) |

### Версия контракта

`contracts/openapi/wiseway-v1.yaml`, `openapi: 3.1.1`, `info.version: 1.0.0` — **без изменений**.
Публичный префикс `/api/v1`, набор путей, operationId, request/response-схемы, examples,
responses, security и tags не менялись.

### Точная коррекция

1. В `components.parameters` добавлен новый компонент (рядом с существующим `CompanyId`):

   ```yaml
   CompanyIdQuery:
     name: company_id
     in: query
     required: true
     description: Компания, к которой относится запрашиваемый список.
     schema: { $ref: '#/components/schemas/Id' }
     example: company-demo-1
   ```

2. `GET /sorting/batches` (`operationId: listSortingBatches`): ссылка в `parameters` изменена
   с `#/components/parameters/CompanyId` на `#/components/parameters/CompanyIdQuery`.
   Итоговый список: `CompanyIdQuery`, `Cursor`, `Limit`.
3. `GET /quarantine` (`operationId: listQuarantineItems`): та же замена.
   Итоговый список: `CompanyIdQuery`, `Cursor`, `Limit`.
4. Существующий path-параметр `CompanyId` (`in: path`, `required: true`, schema `Id`)
   **не изменён** и по-прежнему используется ровно тремя path-level ссылками на путях,
   содержащих `{company_id}`:
   - `/companies/{company_id}/target-directories`;
   - `/companies/{company_id}/target-directories/resolve`;
   - `/companies/{company_id}/dictionaries`.

### V-H: что проверено, команды и результаты

Все проверки ниже — документарные (V-H): полнота diff, ссылки и соответствие
параметр↔путь. Это **не** полная schema validation и **не** WP-02 runner.

1. **Инвентаризация всех ссылок на `CompanyId`** (PowerShell):

   ```powershell
   Select-String -Path contracts/openapi/wiseway-v1.yaml -Pattern "components/parameters/CompanyId"
   ```

   Результат: 5 совпадений —
   `949, 985, 1027` → `CompanyId` (все три — path-level на путях с `{company_id}`);
   `2077, 2523` → `CompanyIdQuery` (обе целевые GET-операции).

2. **Точный diff OAS**:

   ```powershell
   git diff -- contracts/openapi/wiseway-v1.yaml
   ```

   Результат: ровно 3 hunk — 2 однострочные замены `$ref` и 1 добавление компонента
   `CompanyIdQuery`. Других изменений в файле нет.

3. **Целевая структурная проверка (ad-hoc, вне репозитория)** — временный скрипт
   `check.js` (Node 24.20.0, пакет `yaml`) в `%TEMP%\opencode\lt-01-1-verify`,
   разбирает YAML и проверяет параметр↔путь:

   ```powershell
   node check.js "C:\dev\WiseWay-worktrees\e-01\contracts\openapi\wiseway-v1.yaml"
   ```

   Результат: `TOTAL: 25, FAILED: 0`. Проверено, среди прочего:
   YAML парсится; `info.version=1.0.0`; `CompanyIdQuery` определён как
   `name: company_id`, `in: query`, `required: true`, `schema.$ref = Id`;
   обе целевые операции используют `CompanyIdQuery` и не используют path-`CompanyId`;
   все три использования `CompanyId` находятся на путях с `{company_id}`;
   `CompanyIdQuery` используется ровно двумя GET-операциями и ни на одном пути
   с `{company_id}`; все `$ref` параметров разрешаются.
   Скрипт временный, в репозиторий не добавляется.

4. **Проверка пробелов/конфликтов diff**: `git diff --check` (см. отчёт worker; при
   наличии вывода — он указан как есть).

### Ограничения и явно не выполненное

- Полная OpenAPI 3.1 schema validation (refs, unique operationId, examples,
  required/nullable/enums/oneOf, security/CSRF/idempotency/HTTP-responses) —
  **самостоятельный результат WP-02 (LT-02.1)**, здесь не реализована и не объявляется
  пройденной.
- Executable regression для этой правки добавляет LT-02.1.
- Backend/UI/control plane не затрагивались. Staging/commit/push worker не выполняет.

### Статус и следующий владелец

- **Mock/API/QA статус:** не применимо к документарной правке; mock/real/QA-прогоны не
  выполнялись и не заявляются.
- **Оставшиеся дефекты:** B-01 устранён в этом leaf (документарно); B-03 относится к
  LT-01.2.
- **Блокирующая зависимость:** нет.
- **Следующий владелец:** reviewer LT-01.1 (независимая проверка diff и ссылок), затем
  LT-01.2 в рамках WP-01; executable-регрессия — LT-02.1.
