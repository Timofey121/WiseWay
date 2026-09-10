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

## Эталон жизненного цикла справочника (WP-03, LT-03.2b)

`fixtures/synthetic/dictionary_lifecycle.json` — конечный, внутренне связанный
эталон draft/simulation/publication/history/restore поверх неизменяемых
определений LT-03.2a и актёров auth-fixtures:

- `timeline` — связная последовательность Atlas/Nova: create с пустым черновиком
  revision 0, save ожидаемой revision 0 → 1 и 1 → 2, полный READY-тест,
  принятая публикация, restore старой версии → simulate → publish с
  `restored_from_version_id`, ручная правка после restore, очищающая
  `based_on_version_id`;
- `simulations` — тестируемый черновик заменяет только свою активную версию в
  полном наборе компании на всех READY-файлах, включая скрытые/отфильтрованные и
  покрытые другим справочником; явные membership/total/PlanCounts/rows/pages;
  пустой READY даёт warning `EMPTY_READY_SET`; конфликт правил блокирует
  публикацию, одинаковая цель — нет, занятая цель — нет;
- `publishes` — полный активный `RuleSet`, неизменяемая версия и история;
  `batch_bindings` описывает ожидаемое связывание будущей партии (партии ещё
  нет);
- `failures` — устаревшая revision, trim+casefold конфликт имени (без ложного
  межкомпанийного), отдельные stale draft/RuleSet/READY/TTL, NO_SCENARIO
  ack false/true и комментарий 0/501, блокировка конфликтом и повтор ключа
  идемпотентности; у каждого точный request/preconditions/HTTP/operation-схема и
  отсутствие мутации;
- `replays` — потерянный ответ с тем же UUID/пользователем/телом возвращает ту же
  версию до проверки TTL; изменённое тело тем же пользователем — 409
  `IDEMPOTENCY_KEY_REUSED`; другой актор с тем же UUID — новая операция (ключ
  scoped по user), а не конфликт ключа; она оценивается по текущим условиям
  (устаревший тест → 409 `STALE_SIMULATION`). Конфликтные сценарии conflict/
  same-target используют собственные изолированные состояния справочника
  (ревизии 101/102, метка `universe`, без живой истории);
- `coverage` — Q-016…021/029 привязаны к конечным scenario_id. Ожидаемые
  action/audit ID зафиксированы для LT-03.5b, но не являются audit evidence.

`tests/contract/contractlib/dictionary_lifecycle.py` — материализатор по
литеральным ID без runtime-домена. Проверки `FIX-DLC-001/002/003` валидируют
схемы, конечные инварианты, классификацию request-схем и совпадение
сгенерированных публичных примеров. Документированная команда подготовки:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\dictionary_lifecycle.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/dictionaries/`,
`contracts/examples/simulations/` и `contracts/examples/errors/` и привязаны в
`manifest.json` к каноническим схемам. Версия корпуса `1.2.0` не меняется.

## Эталон очереди, readiness и снимков (WP-03, LT-03.3a)

`fixtures/synthetic/queue_selections.json` — конечный, внутренне связанный
эталон очереди компании, наблюдений готовности и снимка выбора поверх
неизменяемых определений LT-03.2a/2b и актёров auth-fixtures:

- `profiles` — три профиля READY `0 / 120 / 1001` плюс изолированный
  `QUEUE-Q022-DECISION-STABILITY`; `status_counts` покрывают все семь состояний
  (`DISCOVERED`, `WAITING_READY`, `READY`, `PROCESSING`, `REQUIRES_DECISION`,
  `RECOVERY_REQUIRED`, `MISSING`), а `matching_count`/`eligible_count` заданы
  отдельно для каждого фильтра (страница ≤100 при общем 120, `MISSING` только
  по явному фильтру, `query_text` — литеральная подстрока); `selectable=true`
  только для стабильного READY/REQUIRES_DECISION без claim, где стабильность —
  явная метадата группы, а не поле `QueueItem`;
- `readiness` — пять конечных наблюдений: два равных size/mtime ≥5 с без
  флага незавершённости → `READY`; изменение/переименование →
  `WAITING_READY` с новой ревизией; незавершённое поступление остаётся
  `WAITING_READY`; claim → `PROCESSING` без смены содержательной ревизии;
- `selection_scenarios` — EXPLICIT одного/нескольких (включая off-page IDs) и
  ALL_MATCHING 120: снимок фиксирует literal membership, `selected_count` и
  `queue_generation`; TTL 300 с; поздний приход и смена фильтра снимок не
  меняют;
- `selection_errors` — 422 `EMPTY_SELECTION`, 422 `BATCH_LIMIT_EXCEEDED` без
  усечения, 409 `SELECTION_CHANGED` до создания, 403 `FORBIDDEN` чужому
  пользователю, 409 `SELECTION_EXPIRED` на реальных preview/batch-операциях,
  404 `NOT_FOUND`; коды сверяются с канонической response-схемой операции;
- `invalid_requests` — schema-отклонение очереди/выбора без компании, пустого и
  1001-элементного EXPLICIT, неизвестного режима и лишних полей;
- `links`/`mutations` — generic cross-links (company/generation/count/membership/
  RuleSet) и негативные мутации, которые обязаны отклоняться валидаторами.

`rule_set` сохраняет принятую идентичность `rule-set-atlas-published` для
следующего leaf preview (LT-03.3b). `tests/contract/contractlib/queue_selections.py`
— материализатор по литеральным ID без matcher/readiness/selection-алгоритма.
Проверки `FIX-QUEUE-001/002/003` валидируют схемы, конечные инварианты,
schema-классификацию запросов и совпадение сгенерированных публичных примеров.
Документированная команда подготовки:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\queue_selections.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/sorting/` и
`contracts/examples/errors/` и привязаны в `manifest.json` к каноническим
схемам. Версия корпуса `1.2.0` не меняется.

## Эталон preview и DIRECT/PREVIEWED preflight (WP-03, LT-03.3b)

`fixtures/synthetic/preview_preflight.json` — конечный, внутренне связанный
эталон не мутирующего расчёта preview и проверок до принятия партии поверх
неизменяемых снимков LT-03.3a и полных определений LT-03.2a/2b:

- `selections` связывают previews с уже принятыми снимками
  `selection-atlas-allmatching-120` (120), `selection-atlas-explicit-one` (1),
  `selection-atlas-explicit-multiple` (3, включая off-page IDs) и добавляют
  явно изолированные наборы `selection-preview-atlas-hetero` (8 источников),
  `selection-preview-atlas-conflict` (1) и `selection-preview-nova-foreign`
  (1, другая компания) — существующие элементы очереди при этом не меняются;
- `previews` — страницы `Preview` с полным published RuleSet
  `rule-set-atlas-published` (120/1/3), изолированным scenario-RuleSet
  `rule-set-atlas-eq-diff` для `RULE_CONFLICT` и Nova-набором для проверки
  компании. `total` равен `selected_count` снимка, страница ≤100 при 120,
  `expires_at` не позже снимка, а `matched_rules`/`selected_rule` всегда
  ссылаются на непустые version_id (черновиков нет);
- `previews[*].rows` покрывают ровно замороженный membership снимка с теми же
  ревизиями, источниками и компанией. Гетерогенный набор демонстрирует все
  четыре `Prediction` (`WILL_MOVE`, `WILL_MANUAL_REVIEW`, `REQUIRES_DECISION`,
  `NOT_READY`) и все три `CollisionDetails` (`EXISTING_TARGET` с метаданными
  занятой цели, `DUPLICATE_PLAN_TARGET` со всеми участниками,
  `MANUAL_REVIEW_NAME` без цели). `NO_SCENARIO` — пустой `matched_rules`,
  `RULE_CONFLICT` — два равных приоритета с разными целями без победителя,
  выбранное правило — минимальный числовой приоритет с устойчивой
  атрибуцией dictionary_id → rule_id;
- `preflight` — 18 сценариев `createSortingBatch`/`createSortingPreview`:
  принятые DIRECT/PREVIEWED и та же сессия другого запроса пользователя
  объявляют только ожидаемый будущий batch ID и RuleSet (payload результата —
  LT-03.4a); отказы до принятия дают 409 `SELECTION_CHANGED` (DIRECT,
  источник изменился/исчез), 409 `STALE_PREVIEW` (PREVIEWED, источник, правила,
  цель или TTL), 409 `SELECTION_EXPIRED`, 409 `INVALID_STATE` (несовместимая
  пара/компания), 404 `NOT_FOUND`, 403 `FORBIDDEN` — всегда с реальным
  запросом, предусловием и отсутствием партии/файловых операций;
- `post_acceptance` описывает пофайловые `SOURCE_CHANGED`/`ALREADY_PROCESSING`
  (а также `TARGET_OCCUPIED`/`MANUAL_REVIEW_NAME_OCCUPIED`) как результат уже
  принятой партии, а не как общий HTTP-отказ;
- `invalid_requests`, `links` и `mutations` классифицируют тела
  `BatchCreateRequest`/`PreviewCreateRequest` и отклоняют негативные мутации
  (total/ревизия/TTL/приоритет/collision/предусловие).

`tests/contract/contractlib/preview_preflight.py` — материализатор по
литеральным ID без matcher/priority/preflight-алгоритма; `_last_suffix` и
проверка цели повторяют документированное DICT-05. Проверки
`FIX-PREVIEW-001/002/003` валидируют схемы, конечные инварианты,
schema-классификацию запросов и совпадение сгенерированных публичных примеров.
Документированная команда подготовки:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\preview_preflight.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/sorting/` (5 Preview) и
`contracts/examples/errors/` (8 ErrorResponse) и привязаны в `manifest.json` к
каноническим схемам. Версия корпуса `1.2.0` не меняется.

## Эталон фактических партий и файловых исходов (WP-03, LT-03.4a)

`fixtures/synthetic/batch_outcomes.json` — конечный, внутренне связанный
эталон принятых партий и пофайловых исходов поверх неизменяемых снимков
LT-03.3a, принятых preflight LT-03.3b и полных определений LT-03.2a/2b:

- три принятых preflight получают реальные `Batch` payloads:
  `PF-DIRECT-FRESH` → `batch-atlas-direct-fresh` (ACCEPTED, 120),
  `PF-PREVIEWED-FRESH` → `batch-atlas-previewed-fresh` (RUNNING, 120, preview
  `preview-atlas-allmatching-120`), `PF-SAME-USER-NEW-SESSION` →
  `batch-atlas-same-user-session` (COMPLETED_WITH_ISSUES, 3). Дополнительно
  объявлен изолированный гетерогенный принятый выбор
  `selection-batch-atlas-hetero` (7) = preview hetero без `NOT_READY`;
- покрыты все пять `BatchState` (`ACCEPTED`, `RUNNING`, `COMPLETED`,
  `COMPLETED_WITH_ISSUES`, `RECOVERY_REQUIRED`), все восемь `OutcomeState` и все
  девять `OutcomeReasonCode`; `state → reason_code`, время, actor и ссылки
  согласованы;
- `counts`: первые пять счётчиков суммируются в `completed_count`,
  `recovery_required` — незавершённые неоднозначные исходы, завершённая партия
  имеет `completed_count == selected_count` и `recovery_required == 0`,
  `RECOVERY_REQUIRED` — `finished_at=null`;
- размещения: `SORTED` совпадает с целью выбранного опубликованного правила
  (каталог + фиксированная основа + последний суффикс); занятая цель не
  перезаписывается и оставляет источник; дубликат плановой цели даёт
  `REQUIRES_DECISION`/`TARGET_OCCUPIED` всем участникам без победителя;
  `NO_SCENARIO`/`RULE_CONFLICT` переносятся в плоскую папку ручного разбора с
  неизменённым basename; занятое имя ручного разбора оставляет источник;
  `QUARANTINED`/`TECHNICAL_ERROR` имеет подтверждённое `actual_location`;
  `RECOVERY_REQUIRED` различает неизвестное (`actual_location=null`) и
  известное (`actual_location=source`) размещение; `SKIPPED`
  (`ALREADY_PROCESSING`/`SOURCE_CHANGED`/`SOURCE_MISSING`) не выполняет
  собственной мутации;
- обе 120-партии описывают точный membership (`100 + 20`); `history`
  (`BatchPage` из `BatchSummary`) сортирована `created_at DESC, batch_id DESC` и
  связывает actor/counts/shared IDs;
- `inventory` — логический контракт ожидаемого инвентаря: для подтверждённых
  переносов источник отсутствует, назначение присутствует, содержимое
  сохранено; content tag (`lt034a-content-*`) детерминирован и не является
  измеренным sha256; файлы не создаются и не читаются.

`tests/contract/contractlib/batch_outcomes.py` — материализатор по литеральным
ID без matcher/executor/recovery-движка. Проверки `FIX-BATCH-001/002/003`
валидируют схемы, конечные state/reason/placement/count/pagination-инварианты,
inventory-контракт и отклоняют 23 негативные мутации. Документированная
команда подготовки:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\batch_outcomes.py --write-examples
```

Сгенерированные примеры лежат в `contracts/examples/sorting/` (9 `Batch` +
1 `BatchPage`) и привязаны в `manifest.json` к каноническим схемам. Версия
корпуса `1.2.0` не меняется.
