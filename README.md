# Wise Way

Wise Way — сервис иерархического поиска по метаданным и ручной сортировки входящих файлов.

В репозитории находится контракт синтетической демоверсии. Сервер и интерфейс ещё не реализованы.

- [OpenAPI 3.1.1](contracts/openapi/wiseway-v1.yaml) — 33 операции: сессии, поиск, справочники, очередь, партии, карантин и журнал. Единственный источник DTO для frontend/backend; примеры встроены.
- [Семантика и границы API](contracts/semantics.md) — правила, которые не выражаются одними типами полей.

Префикс API — `/api/v1`, cookie — `wiseway_session`. Для подключения используйте генератор с поддержкой OpenAPI 3.1. Изменения контракта рассматривают frontend, backend и QA; отдельные копии DTO вручную не поддерживаются.

Проверка контракта (Python 3.11+). Windows (PowerShell), команды проверены на CPython 3.14.7:

```powershell
python -m venv .venv-contract
.\.venv-contract\Scripts\python.exe -m pip install -r tests\contract\requirements.txt
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
```

Portable POSIX-эквивалент (те же шаги):

```sh
python3 -m venv .venv-contract
.venv-contract/bin/python -m pip install -r tests/contract/requirements.txt
.venv-contract/bin/python tests/contract/verify_contract.py
.venv-contract/bin/python -m unittest discover -s tests/contract -p "test_*.py"
.venv-contract/bin/python -m pip check
```

`tests/contract/requirements.txt` — полностью закреплённый транзитивный lock;
`tests/contract/requirements.in` перечисляет прямые зависимости. Runner проверяет
OpenAPI 3.1.1 поддерживаемым валидатором, локальные ссылки, 33 operationId и
соответствие путей, security/CSRF/idempotency, заголовки и связи ошибок с HTTP,
валидирует все встроенные examples против канонических схем и проверяет
семантические инварианты примеров (filename↔location, IDLE/RESULTS counts,
PlanCounts и страницы, RuleSet и rule references, batch/outcome counts и
размещение, quarantine `can_return`, `error.operation_id` и конечные явные
связи selection↔preview↔batch↔audit↔quarantine). Негативные self-тесты
подтверждают, что runner обнаруживает испорченный контракт/payload и что каждый
семантический инвариант срабатывает на своей фикстуре
(`tests/contract/fixtures/semantic_fixtures.py`; для WP-03 переиспользуются
`contractlib.semantic.validate_fixture`, `link_errors` и
`rule_set_consistency_errors`). Исполнение поиска, файловые гарантии
и E2E требуют будущего приложения.

## Синтетический корпус и публичные примеры (WP-03, LT-03.1a)

Версионированный синтетический корпус и публичные примеры API лежат отдельно
от встроенных примеров контракта:

- `fixtures/synthetic/manifest.json` — версия, seed, метод контрольной суммы и
  привязка каждого публичного примера к каноническому указателю
  `#/components/schemas/<Name>` (DTO не копируются); контрольная сумма считается
  по канонической JSON-форме (`json.dumps(..., sort_keys=True)`), поэтому LF- и
  CRLF-checkout дают одинаковый digest;
- `fixtures/synthetic/corpus.json` — компактный метаданный корпус: два
  непересекающихся логических корня Atlas/Nova, контекстно-зависимые
  `marker_id` (уникальны для root+цепочки родителей+raw+kind, как требует
  `contracts/semantics.md`), разный регистр, 103 файла в широкой ветке, четыре
  вида структурных отклонений, служебные объекты вне инвентаря, контроли
  content-only/old-path и явные стадии create/change/rename/move/delete;
- `contracts/examples/` — публичные JSON-примеры auth/config: два WORKER и
  ADMIN, их сессии (инертные CSRF-заглушки, не реальные токены), профили
  N=100/N=10, два корня и пустые состояния roots/companies.

Runner проверяет эти внешние файлы теми же каноническими схемами
(`FIX-EX-001`), все 8 lifecycle before/after `SearchItem` (`FIX-EX-002`),
целостность корпуса (`FIX-CORPUS-001`) и каноническую контрольную сумму
(`FIX-CHK-001`). Загрузчик/материализатор `tests/contract/contractlib/synthetic.py`
раскрывает только объявленные контексты маркеров и явные ID/range-шаблоны
больших регулярных групп и не выполняет поиск, сопоставление или ранжирование.
Документированная команда подготовки (файл `fixtures/synthetic/inventory.json`
не коммитится):

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --write fixtures\synthetic\inventory.json
```

## Точные поисковые ожидания (WP-03, LT-03.1b)

`fixtures/synthetic/search_expectations.json` — конечный независимый эталон
поверх корпуса LT-03.1a:

- `search_scenarios` — литеральные `SearchResponse`: точные упорядоченные
  `item_ids`, `total`, `returned_count`, `result_limit`, `limited` и варианты
  `next_facet` (marker_id + точный count) для IDLE/RESULTS/N10/N100, AND,
  фраз, границ токенов, ранжирования (ручные score 10/5/2/20/4), tie-break
  natural/raw path, ручных сортировок NAME/SIZE/MODIFIED_AT/PATH, raw-case,
  optional tail, Nova Area, UNRECOGNIZED-терминала, четырёх issue-типов и
  freshness CURRENT/UPDATING/STALE;
- `facet_scenarios` — литеральные `FacetResponse` для родителей уровня,
  альтернатив, `facet_prefix` и UNRECOGNIZED последним; терминальная опция
  связана с первым отклонением литерально (`unrecognized_sources`);
- `auth_scenarios`, `error_scenarios` — точные пары HTTP/`error.code` и
  безопасные `ErrorResponse` (401/403/409/422/429/500/503); код проверяется
  против канонической response-схемы конкретной операции (`CSRF_FAILED` →
  logout, `FORBIDDEN` → login с запрещённым Origin);
- `race_scenarios` — сценарии `request_state_id` (последний ответ scope
  побеждает, разрешённый retry получает новый ID);
- `lifecycle_scenarios` — ожидания create/change/rename/move/delete;
- `format_samples` — Q-042 литеральные UI-значения размера/даты/display path;
- `sort_profiles` — stand-alone comparator-таблица для tie-break по `item_id`
  (два логических `SearchItem` с одинаковым display sort key, не инвентарь);
- `coverage` — каждый Q-001…014/042/043 привязан к конечным scenario_id.

`SearchItem.markers` в корпусе содержит только распознанные VALUE-родителей;
каталожные UNRECOGNIZED-терминалы существуют отдельно для
`selected_markers`/фасетов.

`tests/contract/contractlib/search_expectations.py` — материализатор: он
собирает ответы **только по литеральным ID** (item/marker/facet), не вычисляя
membership, ranking или facets. Проверки `FIX-SRCH-001/002` валидируют схемы,
counts, ID и совпадение сгенерированных публичных примеров с закоммиченными.
Документированная команда подготовки публичных примеров:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\search_expectations.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/search/` и
`contracts/examples/errors/` и привязаны в `manifest.json` к каноническим
схемам. Списки natural/русской сортировки в `search_inputs` остаются
неупорядоченными кандидатными входами; точный порядок задают сценарии.

## Эталоны правил и целей (WP-03, LT-03.2a)

`fixtures/synthetic/rule_expectations.json` — конечный независимый эталон
правил, справочников и целей поверх корпуса LT-03.1a:

- `dictionaries`/`versions`/`rule_sets` — два опубликованных справочника Atlas
  (два словаря) и один Nova с неизменяемыми версиями, полными определениями
  правил и полным активным `RuleSet` компании (members отсортированы по
  `dictionary_id`); отдельные сценарные варианты имеют собственные version и
  rule_set ID. Каждая версия помечена `role`: `published` — живая история
  словаря, `scenario` — изолированный тестовый универсум для будущих
  simulation fixtures. Публичный `Dictionary.versions_count` считает только
  `published`; сценарные версии в основную историю не входят;
- `target_directories` — разрешённые целевые каталоги компаний;
- `sources` — идентичность/относительный вход каждого сценария (часть
  привязана к реальным `SearchItem` корпуса);
- `rule_scenarios` — литеральные `matched_rule_refs`, `selected_rule`,
  `target`, `target_basename`, `predicted_state` и `reason_code` для
  BASENAME/RELATIVE_PATH, whole-field/`*`/`?`, нуля/множества `*` и перехода
  через слеш (`Archive*Reports/*` матчит полный путь, включая basename;
  trailing-only `Archive*Reports` — отдельный отрицательный контроль),
  нормализации слешей и casefold без NFC, приоритетов 1/1000, равного
  приоритета с одинаковой и разной целью, суффиксов
  `archive.tar.gz`/`.env`/`README`/`name.`/`.TXT` и точечной основы;
- `target_scenarios` — резолвер цели: разрешённые каталоги и отклонения
  422 `INVALID_TARGET`/`PATH_OUTSIDE_ROOT`/`VALIDATION_ERROR`, привязанные к
  response-схеме `resolveTargetDirectory`;
- `invalid_rule_cases` — недопустимые `**`/regex/скрытый OR/escape,
  приоритеты и длины основы; схемно-невалидные случаи помечены
  `schema_rejected=true` и проверяются на отклонение схемой `Rule`, остальные
  доменные случаи положительно не проверяются;
- `coverage` — Q-015/Q-018/Q-044 привязаны к конечным scenario_id.

`tests/contract/contractlib/rule_expectations.py` — материализатор: он
собирает `Rule`/`Dictionary`/`DictionaryVersion`/`RuleSet`/`TargetDirectory`/
`PlanRow`/`ErrorResponse` **только по литеральным ID**, не выполняя matcher,
выбор приоритета, разрешение конфликта или построение итогового имени.
Проверки `FIX-RULE-001/002` валидируют схемы, конечные инварианты и совпадение
сгенерированных публичных примеров с закоммиченными. Документированная команда
подготовки публичных примеров:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\rule_expectations.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/dictionaries/`,
`contracts/examples/targets/` и `contracts/examples/errors/` и привязаны в
`manifest.json` к каноническим схемам.
