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

## LT-01.2 — согласование examples Simulation / SelectionSnapshot / Preview (B-03)

### Задача и покрытые требования

- **Leaf:** LT-01.2 (WP-01, Epic E-01). **Status на момент handoff:** IN_PROGRESS.
- **Дефект:** B-03 — в `simulation_no_scenario`/`simulation_rule_conflict` `filename` не
  совпадал с basename `source.relative_path`; `simulation_rule_conflict` ссылался на
  `dictionary-demo-2/version-demo-9/rule-demo-9`, которой не было в его `base_rule_set`;
  связанные по `selection_id` examples selection/preview показывали 120 и 1.
- **Основание:** D-04, D-06; API §6/7; QA §4; OAS Simulation/PlanRow/RuleSet/
  SelectionSnapshot/Preview.
- **Бизнес-семантика не изменена:** paths, operationId, components/schemas, DTO-поля,
  responses и security не менялись. Правки — только в `value` встроенных examples.

### Изменённые файлы

| Файл | Характер изменения |
|---|---|
| `contracts/openapi/wiseway-v1.yaml` | изоляция `rule-set-demo-conflict`, сценарные `ready_snapshot_id`, 1 `filename`, request/response examples `createSortingSelection` |
| `docs/team/E-01_CONTRACT_HANDOFF.md` | этот раздел |

### Версия контракта

`openapi: 3.1.1`, `info.version: 1.0.0` — **без изменений**. Публичный префикс `/api/v1`,
набор путей, operationId, схемы и responses не менялись.

### Перечень точечных коррекций

1. `simulation_no_scenario`: `source.relative_path`/`display_path` приведены к
   `Incoming/atlas/unmatched.bin` (basename = `filename`). `filename` остаётся
   `unmatched.bin`; файл не содержит `invoice` и не совпадает с черновой маской
   `*invoice*` (rule-demo-1), поэтому `NO_SCENARIO` правдоподобен.
2. `simulation_no_scenario`: `ready_snapshot_id` → `ready-snapshot-demo-no-scenario`
   (своя идентичность item).
3. `simulation_rule_conflict`: `base_rule_set.rule_set_id` →
   `rule-set-demo-conflict` — изолированный RuleSet из двух членов
   `dictionary-demo-1/version-demo-2` и `dictionary-demo-2/version-demo-9`.
   Published-ref `dictionary-demo-2/version-demo-9/rule-demo-9` входит именно в него.
4. `simulation_rule_conflict`: `filename: ambiguous.txt` → `invoice-2031.TXT`
   (совпадает с basename `source.relative_path`); `ready_snapshot_id` →
   `ready-snapshot-demo-conflict`.
5. `simulation_occupied_target`: `ready_snapshot_id` →
   `ready-snapshot-demo-occupied`; RuleSet остаётся `rule-set-demo-2` (один член).
6. `components/examples/SharedSimulationWillMove` и `published_dictionary.rule_set`:
   добавление `dictionary-demo-2/version-demo-9` откатано — `rule-set-demo-2` снова
   единый одночленный набор (`dictionary-demo-1/version-demo-2`).
7. `POST /sorting/selections` request example `explicit`: 2 items → 1 item
   (`item-001`, `item_revision: 3`); summary уточнён.
8. `POST /sorting/selections` response: вместо одного `created` два примера —
   `explicit` (`selection-001`, EXPLICIT, `selected_count: 1`) и `allMatching`
   (`selection-allmatching-120`, ALL_MATCHING, `selected_count: 120`). 120-пример
   сохранён под отдельным `selection_id`; связь с request `allMatching`
   (`expected_eligible_count: 120`) явная по имени примера.

### Конечная таблица связей

RuleSet ID → членство (все вхождения совпадают):

| rule_set_id | members |
|---|---|
| `rule-set-demo-2` | `dictionary-demo-1/version-demo-2` |
| `rule-set-demo-conflict` | `dictionary-demo-1/version-demo-2`, `dictionary-demo-2/version-demo-9` |
| `ruleset-5` | `dictionary-001/version-003` |

Конечные сценарии — отдельные состояния (свои item/`ready_snapshot_id`/RuleSet), а не один
вход с противоречивым выходом (`version_id: null` — только тестируемый черновик
`dictionary-demo-1`):

| simulation | item | source / filename | base RuleSet | ready_snapshot | refs → outcome |
|---|---|---|---|---|---|
| `simulation-demo-1` | `queue-item-demo-1` | `Incoming/atlas/invoice-2031.TXT` | `rule-set-demo-2` | `ready-snapshot-demo-1` | draft rule-demo-1 → WILL_MOVE |
| `simulation-demo-no-scenario` | `queue-item-demo-2` | `Incoming/atlas/unmatched.bin` | `rule-set-demo-2` | `ready-snapshot-demo-no-scenario` | `[]` → NO_SCENARIO |
| `simulation-demo-rule-conflict` | `queue-item-demo-3` | `Incoming/atlas/invoice-2031.TXT` | `rule-set-demo-conflict` | `ready-snapshot-demo-conflict` | draft rule-demo-1 + `dictionary-demo-2/version-demo-9/rule-demo-9` → RULE_CONFLICT |
| `simulation-demo-occupied` | `queue-item-demo-4` | `Incoming/atlas/invoice-2031.TXT` | `rule-set-demo-2` | `ready-snapshot-demo-occupied` | draft rule-demo-1 → TARGET_OCCUPIED |

`selection_id` → счётчики (selection / preview / batch):

| selection_id | SelectionSnapshot | Preview.total | Batch.selected_count |
|---|---|---|---|
| `selection-001` | EXPLICIT 1 | `preview-001` = 1 | `batch-001` = 1 |
| `selection-allmatching-120` | ALL_MATCHING 120 | — | — |
| `selection-batch-running` | — (нет примера) | — | `batch-running` = 3 |
| `selection-batch-recovery` | — (нет примера) | — | `batch-recovery` = 2 |
| `selection-batch-mixed` | — (нет примера) | — | `batch-mixed` = 8 |

Request ↔ response examples `createSortingSelection`:

| request example | значение | response example |
|---|---|---|
| `explicit` | EXPLICIT, 1 item | `explicit` → `selection-001`, count 1 |
| `allMatching` | ALL_MATCHING, expected 120 | `allMatching` → `selection-allmatching-120`, count 120 |

Preview/batch-цепочка (`ruleset-5`) не менялась; nullable-цели (`target: null`,
`planned_target: null`, `actual_location: null`) не подменялись выдуманным размещением.

### V-H: что проверено, команды и результаты

Проверки документарные (V-H) и ad-hoc; это **не** полная schema validation и **не** WP-02
runner.

1. `git diff --check` → exit 0 (пробелы/конфликты отсутствуют).
2. Ad-hoc структурная проверка (Node 24.20.0, пакет `yaml` из
   `%TEMP%\opencode\lt-01-1-verify\node_modules`; скрипт временный, вне репозитория):

   ```powershell
   node "C:\Users\CheSeVe\AppData\Local\Temp\opencode\lt-01-2-verify\check.js" "C:\dev\WiseWay-worktrees\e-01\contracts\openapi\wiseway-v1.yaml"
   ```

   Результат: `TOTAL: 56, FAILED: 0`. Среди проверок: `filename` = basename
   `source.relative_path` для всех PlanRow; `rule_set_id` → единое членство; все
   published `RuleReference` в Simulation/Preview/Batch входят в RuleSet соответствующего
   примера, `version_id: null` — только для тестируемого черновика; `selected_count` =
   `preview.total` = `batch.selected_count` для общих `selection_id`; 120 ALL_MATCHING
   сохранён под отдельным ID и связан с request `allMatching`; у каждой simulation свой
   `ready_snapshot_id`; в `rule_conflict` published-ref второго справочника входит в
   `rule-set-demo-conflict`.
3. Резолвинг всех `$ref` (`refs.js` в той же временной папке): `refs=815 unresolved=0`.
4. Инвентаризация связей (`inventory.js` в той же временной папке) — источник таблиц выше.
5. Регрессия LT-01.1:

   ```powershell
   node "C:\Users\CheSeVe\AppData\Local\Temp\opencode\lt-01-1-verify\check.js" "C:\dev\WiseWay-worktrees\e-01\contracts\openapi\wiseway-v1.yaml"
   ```

   Результат: `TOTAL: 25, FAILED: 0` (B-01 не затронут).
6. V-H семантическая сверка вручную (без domain matcher): черновая маска `rule-demo-1`
   = `*invoice*` (BASENAME). `unmatched.bin` не содержит `invoice` → NO_SCENARIO
   правдоподобен; `invoice-2031.TXT` содержит `invoice` → RULE_CONFLICT/TARGET_OCCUPIED
   правдоподобны. Это проверка правдоподобия примеров, а не реализация matcher.

### Ограничения и явно не выполненное

- Полная OpenAPI 3.1 schema validation (refs, unique operationId, examples,
  required/nullable/enums/oneOf, security/CSRF/idempotency/HTTP-responses) —
  **самостоятельный результат WP-02 (LT-02.1)**; здесь не реализована и не объявляется
  пройденной. V-S ещё не выполнена.
- Executable regression для этих examples добавляет LT-02.2.
- Backend/UI/control plane не затрагивались. Staging/commit/push worker не выполняет (D-06).

### Исправление по замечаниям reviewer (repair cycle 1)

- **Finding 1** — NO_SCENARIO был переименован в `invoice-2031.TXT`, который совпадает с
  маской `*invoice*` (невозможный no-scenario). Устранено: no-scenario использует
  `unmatched.bin` и в `filename`, и в `source.relative_path`/`display_path`.
- **Finding 2** — добавление `dict2/version9` во все вхождения `rule-set-demo-2` давало
  взаимно несогласованные matched rules для одного `invoice`-файла/ревизии черновика в
  move/conflict/occupied. Устранено: конфликт изолирован в `rule-set-demo-conflict`,
  `rule-set-demo-2` возвращён к одному члену; каждому сценарию дан свой
  `ready_snapshot_id`.
- Доменный matcher не вводился: сценарии описаны как конечные отдельные состояния.

### Статус и следующий владелец

- **Mock/API/QA статус:** не применимо к документарной правке; mock/real/QA-прогоны не
  выполнялись.
- **Дефект B-03:** замечания reviewer устранены в examples; **документарно закрытым B-03
  не объявляется до независимого PASS** этого repair-цикла. Статус leaf — IN_PROGRESS.
- **Блокирующая зависимость:** нет.
- **Следующий владелец:** повторный reviewer LT-01.2 (независимая проверка diff, examples
  и таблиц), затем WP-02; executable-регрессия — LT-02.2.
