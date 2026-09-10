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

## LT-02.1 — воспроизводимая структурная/schema-проверка контракта

### Задача и покрытые требования

- **Leaf:** LT-02.1 (WP-02, Epic E-01). **Status на момент handoff:** IN_PROGRESS.
- **Цель:** заменить несуществовавшую команду README (B-02) исполняемым runner,
  который валидирует весь существующий OAS из 33 операций и его встроенные examples.
- **Основание/требования:** README; FE-01/02; API §2/11/12; PLAN §7; Q-043 S; MATRIX
  G-1/G-6, V-S; OAS целиком. Backend и промежуточная QA-подпись не требуются.

### Изменённые файлы

| Файл | Характер |
|---|---|
| `tests/contract/verify_contract.py` | CLI-runner (README entry point) |
| `tests/contract/contractlib/*.py` | переиспользуемые helpers: loading/refs, schema-validation, structure, examples, report, expectations |
| `tests/contract/test_verify_contract.py` | positive/negative self-тесты (stdlib `unittest`) |
| `tests/contract/requirements.in`, `tests/contract/requirements.txt` | прямые зависимости и полностью закреплённый транзитивный lock |
| `README.md` | реальные команды Windows и POSIX-эквивалент |
| `docs/team/E-01_CONTRACT_HANDOFF.md` | этот handoff |

OAS `contracts/openapi/wiseway-v1.yaml` **не изменялся**; точечная нормализация не
потребовалась.

### Версия контракта

`openapi: 3.1.1`, `info.version: 1.0.0`, 33 operationId, префикс `/api/v1` — без
изменений. Публичные пути, DTO, examples, security и responses не правились.

### Что проверяет runner (V-S)

Структурные проверки (идентификаторы `OAS-*`): OpenAPI 3.1.1 через поддерживаемый
`openapi-spec-validator==0.9.0`; метаданные/сервер/`cookieAuth`; отсутствие внешних
ссылок и разрешимость всех локальных `$ref` (preflight до third-party валидатора);
ровно 33 уникальных operationId и точное соответствие метод/путь; соответствие
`{path}`-переменных path-параметрам; эффективный обязательный `company_id` со схемой
`Id` ровно на двух query-GET (`listSortingBatches`/`listQuarantineItems`) и на
четырёх path-потребителях (`listTargetDirectories`, `resolveTargetDirectory`,
`listDictionaries`, `createDictionary`); анонимны только `getHealth`/`login`,
защищённые операции строго `[{cookieAuth: []}]` без пустой альтернативы; точные
наборы CSRF (10 мутаций) и Idempotency-Key (publish/batch/return); `X-Request-ID` и
`Cache-Control: no-store` на всех ответах, `Retry-After` на 429; соответствие
`error.code` HTTP-статусу; ожидаемые success-статусы и точный набор объявленных
HTTP-статусов на операцию; обязательные request body; закрытые объекты
(`additionalProperties: false`); канонические ограничения `Id`/`Revision`/`Count`/
`Instant`/`RelativeDirectory`/`RelativeFilePath` и `Limit` 1..100.

Examples: все встроенные request/response/parameter/header/schema examples (127 шт.)
валидируются против канонической схемы через `jsonschema` 2020-12 с format-checker
(`date-time`, `uuid`), с корректной семантикой nullable-union, `oneOf` и закрытых
объектов. Внешние `externalValue` запрещены в любом месте; непривязанные к схеме
component examples отклоняются как непроверяемые.

### V-S: точные команды и фактические результаты

Windows (PowerShell), Python 3.14.7, `.venv-contract`:

```powershell
python -m venv .venv-contract
.\.venv-contract\Scripts\python.exe -m pip install -r tests\contract\requirements.txt
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
```

- `verify_contract.py` → exit 0, `RESULT: PASS (19 checks, 0 failures)`, 127 examples.
- `unittest discover` → `Ran 45 tests ... OK` (45/45).
- `pip check` → `No broken requirements found.`
- Чистая воспроизводимость: отдельный пустой venv, `pip install -r
  tests/contract/requirements.txt` (exit 0), затем те же три команды — тот же
  результат (PASS/45 OK/No broken requirements).

### Negative regression (доказательство, что runner ловит дефекты)

Тесты подтверждают обнаружение: исходного B-01 (`CompanyId in:path` на
`/sorting/batches` без `{company_id}`), удаления `CompanyIdQuery` из
`listSortingBatches`/`listQuarantineItems` (по одному и из обоих), подмены его схемы
на неограниченную строку, неверных `required`/`in` и поломки path-потребителя,
дубликата/отсутствия operationId, внешней и неразрешимой ссылки (в т.ч. что
third-party валидатор не вызывается при non-local ref — mock-spy), лишней анонимной
операции и пустой security-альтернативы в обоих порядках, пропавшего
CSRF/Idempotency-Key, пропавшего `X-Request-ID`, неверной связи error.code↔HTTP,
неверного success-статуса, отсутствующего объявленного HTTP-статуса, открытого
объекта, испорченного example, `externalValue` (включая непривязанный component
example) и непривязанного component example. Payload-уровень: неизвестные поля
отклоняются; отсутствующее required отклоняется, разрешённый `null` принимается;
enum; оба варианта `SelectionRequest`/`BatchCreateRequest` и их загрязнённые
комбинации; границы `Id`, `Count` (0…2^53−1), `Instant` (format+`Z`), `Limit`,
`RelativeFilePath`. CLI проверяется subprocess-тестами (PASS/FAIL/exit 2).

### Repair cycle 1 (устранение 3 blocking false negatives)

- **CompanyId (B-01).** Раньше проверялось только определение component-параметра;
  удаление ссылки из операции или подмена схемы на `type: string` проходили. Добавлен
  `OAS-PARAM-001`: эффективные параметры каждой операции обязаны давать ровно один
  `company_id` с `required: true` и схемой `$ref Id` — query для двух GET-списков,
  path для четырёх потребителей `{company_id}`. Добавлены мутации на удаление,
  схему, `required` и `in`.
- **Security.** Раньше `[{}, {cookieAuth: []}]` в любом порядке проходило, т.к.
  требовалось лишь наличие `cookieAuth` среди альтернатив. `OAS-SEC-001` теперь
  требует ровно `[{cookieAuth: []}]` для защищённых операций и отвергает пустую
  альтернативу; добавлены регрессии для обоих порядков.
- **Внешние ссылки.** `openapi-spec-validator` запускался до локальной проверки
  ссылок и мог разрешать attacker-controlled remote `$ref`. `OAS-REF-001/002` теперь
  выполняются preflight до third-party валидатора, а `OAS-BASIC-001` не вызывает
  `validate()` при наличии non-local ref. Тест с mock-spy подтверждает, что
  `openapi_spec_validator.validate` не вызывается.
- **Nonblocking внутри границы.** `OAS-RESP-001` фиксирует точный набор объявленных
  HTTP-статусов на операцию (reviewed baseline в `expectations.py`, не runtime).
  `OAS-EX-002` отвергает `externalValue` в любом месте и непривязанные component
  examples. CLI печатает точное число проверенных examples (`Examples: 127 ...`).

### Ограничения и явно не выполненное

- Это LT-02.1: структурная/schema-проверка и примеры. Семантические инварианты
  примеров (filename/location, IDLE/counts, PlanCounts, selection↔preview↔batch)
  — следующий LT-02.2; здесь не реализованы и не заявляются.
- Backend/UI/control plane/backlog не затрагивались; staging/commit/push worker не
  выполняет (D-06). Mock/real/QA-прогоны не выполнялись.

### Статус и следующий владелец

- **Mock/API/QA статус:** не применимо; проверка контракта — не E2E и не real API.
- **Оставшиеся дефекты:** B-02 устранён (README-команды существуют и выполняются).
- **Блокирующая зависимость:** нет.
- **Следующий владелец:** reviewer LT-02.1; затем LT-02.2 (семантические инварианты)
  поверх переиспользуемых helpers `contractlib`.

## LT-02.2 — семантические инварианты встроенных examples и конечные фикстуры

### Задача и покрытые требования

- **Leaf:** LT-02.2 (WP-02, Epic E-01). **Status на момент handoff:** IN_PROGRESS.
- **Цель:** поверх канонической schema-validation LT-02.1 применить к каждому
  релевантному встроенному example явные проверки согласованности, которые схема
  выразить не может, и подтвердить их конечными positive/negative-фикстурами без
  реализации matcher/ranking/домена.
- **Основание/требования:** D-06; API §4/6–11; SEM поиск/правила/очередь/повторы;
  MATRIX Q-011/017/024/029/038/043 S; OAS SearchResponse/PlanCounts/Simulation/
  Preview/Batch/OutcomeCounts/Outcome/RuleSet/ErrorDetails/AuditEvent/QuarantineItem.
- **Дефект B-03:** уже устранён в LT-01.2; LT-02.2 добавляет исполняемую регрессию
  этих согласований.

### Изменённые файлы

| Файл | Характер |
|---|---|
| `tests/contract/contractlib/semantic.py` | новый модуль: переиспользуемые семантические валидаторы, конечные явные связи, интеграция в отчёт |
| `tests/contract/contractlib/examples.py` | публичный `resolve_example_value`; удалён лишний пустой EOF |
| `tests/contract/contractlib/verify.py` | `run_checks` вызывает `run_semantic_checks` |
| `tests/contract/contractlib/report.py` | поле `semantics_checked` |
| `tests/contract/contractlib/__init__.py` | экспорт semantic API |
| `tests/contract/verify_contract.py` | строка `Semantics: N example(s) checked` |
| `tests/contract/fixtures/semantic_fixtures.py`, `tests/contract/fixtures/__init__.py` | конечные positive/negative-фикстуры |
| `tests/contract/test_semantics.py` | тесты фикстур, покрытия и мутаций |
| `README.md` | описание семантического слоя и переиспользования в WP-03 |
| `docs/team/E-01_CONTRACT_HANDOFF.md` | этот раздел |

OAS `contracts/openapi/wiseway-v1.yaml` **не изменялся**: новых дефектов примеров
сверх устранённых WP-01/B-03 не обнаружено, коррекция OAS не потребовалась.

### Версия контракта

`openapi: 3.1.1`, `info.version: 1.0.0`, 33 operationId, 127 examples — без изменений.

### Что проверяет семантический слой

`contractlib.semantic` сначала прогоняет канонический `validate_value`, а затем
применяет к каждому примеру проверки (check `OAS-SEM-001`):

- `filename` = basename `location.relative_path`/`source.relative_path`, включая
  вложенные `FileMetadata` в `CollisionDetails` (рекурсивно);
- `SearchResponse`: IDLE ⇒ `total=null`, пустые `items`, `returned_count=0`,
  `limited=false` и непустой первый `next_facet`; RESULTS ⇒
  `returned_count=items.length=min(total,result_limit)`, `limited=(total>result_limit)`,
  `items.length≤result_limit`;
- `PlanCounts`: сумма первых четырёх счётчиков = `total`; `rule_conflicts`/`no_scenario`
  — дополнительные и не прибавляются повторно; страница `rows` не превышает `total`
  (`null`-cursor не трактуется как полнота набора);
- `RuleSet`: члены отсортированы и уникальны по `dictionary_id`, `version_id` непуст;
- глобально один `rule_set_id` всегда обозначает одну компанию и один состав
  (`OAS-SEM-003`; helper `rule_set_consistency_errors` для WP-03);
- rule references: `version_id=null` только для тестируемого черновика Simulation;
  published-ссылки Preview/Simulation/Batch входят в охватывающий `RuleSet`;
  `selected_rule` ∈ `matched_rules`; `company_id` строк согласован с набором/ответом;
- `Batch`/`BatchSummary`: `completed_count` = сумма первых пяти `OutcomeCounts`
  (recovery исключён), `completed_count≤selected_count`,
  `completed_count+recovery_required≤selected_count`, терминальный статус ⇒
  `completed_count=selected_count`, ACCEPTED ⇒ 0 завершённых, `recovery_required>0` ⇒
  статус `RECOVERY_REQUIRED`, страница `outcomes` не превышает объявленные counts;
- `Batch.outcomes[].matched_rule`: опубликованная ссылка (`version_id≠null`) обязана
  входить в `batch.rule_set.members`; null-версия вне Simulation отклоняется;
- `Outcome`: SORTED/MANUAL_REVIEW/QUARANTINED имеют подтверждённый `actual_location`;
  `actual_location=null` означает «размещение не установлено» и **не** запрещает известное
  размещение; SKIPPED и REQUIRES_DECISION не перемещают файл, поэтому известное
  `actual_location` обязано совпадать с `source` (null также допустим). Для
  PENDING/PROCESSING никакого запрета не вводится (нет нормативного основания);
- `QuarantineItem`: `can_return=false` ⇔ непустой `recovery_operation_id`;
- `ErrorDetails`: `operation_id=null` до регистрации операции; `RECOVERY_REQUIRED`
  имеет непустой `operation_id` и `retryable=false`;
- `QueueResponse`: `counters` согласованы с `status_counts` (attention =
  REQUIRES_DECISION+RECOVERY_REQUIRED); `selectable=true` только для
  READY/REQUIRES_DECISION без активного claim.

Check `OAS-SEM-002` проверяет конечные явные связи между примерами (только там, где
совпадают конкретные ID; независимые сценарии намеренно не связываются):
request↔response `/search` и `/search/facet` (`request_state_id`/`root_id`/
`schema_set_version`); selection↔preview↔batch (`selection_id`, `company_id`,
`selected_count`=`total`=`selected_count`, `preview_id`, `rule_set_id`); повторный GET
preview/simulation = POST-ответ; quarantine list↔return (`item_id`, `company_id`,
`filename`, `original_location`=`source`, `revision`↔`expected_revision` — сравнение
несуществующего `QueueItem.source_attempt_id` удалено); audit `BATCH_ACCEPTED`↔batch
(`batch_id`, `company_id`, `rule_set_id`). Отсутствующий endpoint или поле объявленной
связи теперь **ошибка** (`link_errors`), а не молчаливый skip; независимые примеры
просто не входят в реестр связей.

Корреляция audit `QUARANTINE_RETURNED` (`operation_id`=`return_operation_id`,
`source_attempt_id` связывает с исходной попыткой сортировки) в канонических examples
общих ID не имеет — это **осознанная standalone-граница**. Она доказана явной конечной
linked-парой фикстур (`return-audit-positive`/`return-audit-negative`, helper
`link_errors`) для переиспользования в WP-03.

`validate_fixture(registry, schema_pointer, value)` — точка переиспользования для
WP-03: возвращает `(schema_errors, semantic_errors)`, семантика выполняется только
для schema-valid payload. `link_errors(source, target, fields, name)` проверяет
linked-пару и падает на отсутствующем поле; `rule_set_consistency_errors(rule_sets)`
проверяет единый состав одного `rule_set_id`.

### Конечные фикстуры

`tests/contract/fixtures/semantic_fixtures.py` — 48 schema-valid payloads,
сгруппированных в 14 инвариантов (filename-basename, search-idle, search-results,
plan-counts, plan-page, ruleset-members, rule-references, batch-completion,
batch-rule-references, outcome-placement, quarantine-can-return, error-operation-id,
error-recovery, queue-consistency). Каждый инвариант имеет ≥1 positive и ≥1 negative;
negative остаётся schema-valid и нарушает ровно одну семантическую проверку с
проверяемым подстроковым маркером. Дополнительно — 2 конечные linked-пары
`return-audit-positive`/`return-audit-negative` для корреляции
quarantine-return↔audit `QUARANTINE_RETURNED`.

### V-S: точные команды и фактические результаты

Windows (PowerShell), Python 3.14.7, `.venv-contract`:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
git diff --check
```

- `verify_contract.py` → exit 0, `RESULT: PASS (22 checks, 0 failures)`,
  `Examples: 127 ...`, `Semantics: 127 example(s) checked` (OAS-SEM-001/002/003).
- `unittest discover` → `Ran 72 tests ... OK` (45 LT-02.1 + 27 LT-02.2).
- `pip check` → `No broken requirements found.`
- `git diff --check` → exit 0.

### Negative regression (доказательство, что проверки не пусты)

`test_semantics.py` мутирует один факт канонического документа и подтверждает
падение конкретной проверки: IDLE без `next_facet`; неверный `returned_count`;
`total`≠сумма первых четырёх PlanCounts; `completed_count`≠сумма первых пяти;
`Batch.outcomes[].matched_rule` вне `rule_set.members`; SKIPPED с подтверждённым
перемещением (`actual_location`≠`source`); `can_return=false` без
`recovery_operation_id`; `RECOVERY_REQUIRED` без `operation_id`; несовпадение
`selection_id`/`rule_set_id` (`OAS-SEM-002`); несовместимый состав одного
`rule_set_id` (`OAS-SEM-003`).

Кроме точечных мутаций, **каждая** объявленная связь `finite_links()` покрыта
параметризованно: несовпадение значения, исчезновение endpoint и исчезновение
обязательного поля — все три обязаны дать `OAS-SEM-002`. Фикстурные тесты
дополнительно проверяют, что shape-дефект ловится канонической schema, а не
семантикой, и что null-версия `Batch.outcomes[].matched_rule` отклоняется
семантически (schema сужает её отдельно).

### Ограничения и явно не выполненное

- Реализованы только проверки согласованности примеров; matcher/ranking/readiness/
  totals/FS/snapshot membership не реализуются и не заявляются.
- Конечные явные связи не являются выводом о независимых сценариях; standalone
  примеры (runningPartial/recoveryRequired/mixed/`selection-allmatching-120` и др.)
  намеренно не связаны. Audit-пример `BATCH_ACCEPTED` связан с batch; канонического
  audit `QUARANTINE_RETURNED` с общими `return_operation_id`/`source_attempt_id` нет,
  поэтому корреляция возврата доказана linked-парой фикстур, а не выдуманной связью.
- Backend/UI/control plane/backlog не затрагивались; staging/commit/push worker не
  выполняет (D-06). Mock/real/QA-прогоны не выполнялись.
- WP-03 выполняется отдельно от этой проверки: внешние `contracts/examples/`/
  `fixtures/synthetic/` создаются его leaf-ами (см.
  `WP-03_SYNTHETIC_HANDOFF.md`); здесь описана только семантическая проверка
  встроенных примеров OAS.

### Статус и следующий владелец

- **Mock/API/QA статус:** не применимо; это статическая проверка контракта.
- **Оставшиеся дефекты:** новых дефектов examples не найдено; B-03 покрыт регрессией.
- **Блокирующая зависимость:** нет.
- **Следующий владелец:** reviewer LT-02.2 (независимая проверка семантики, фикстур,
  мутаций и отсутствия OAS-правок); затем WP-03 поверх `contractlib.semantic`.
