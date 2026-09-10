# WP-03 / LT-03.1a — handoff: синтетический корпус и публичные примеры

Файл фиксирует результат leaf LT-03.1a по правилам FE §7: задачу, изменённые
файлы, версии/seed, что именно проверено, точные команды и результаты,
ограничения и следующий владелец. «Готово» без evidence не используется.

## Задача и покрытые требования

- **Leaf:** LT-03.1a (parent LT-03.1, WP-03, Epic E-01). **Status:** IN_PROGRESS
  (публикация отложена решением D-06).
- **Цель:** версионированный конечный синтетический метаданный корпус и
  публичные примеры auth/config, которые следующие leaf-ы (LT-03.1b и далее)
  используют как независимый источник ожиданий. Matcher/ranking/домен не
  реализуются.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.1/LT-03.1a; D-03/D-06;
  TZ §5/6.3/12; QA §4/5; API §2–4/12; MATRIX Q-001/004/012/014/042/043;
  OAS Actor/Session/AppConfig/Root/Company/SearchItem/Marker/StructureIssue;
  `contracts/semantics.md` (поиск: `marker_id` стабилен для
  root/parents/raw/kind в одной версии схемы).

## Изменённые файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/corpus.json` | компактный метаданный корпус: `marker_model` (алфавит + контексты), файлы, cohort-шаблоны, служебные объекты, контроли, lifecycle, search_inputs |
| `fixtures/synthetic/manifest.json` | версия/seed, канонический checksum-метод и привязка публичных примеров к каноническим schema pointers |
| `contracts/examples/auth/*.json` | 3 Actor, 3 Session, 3 LoginRequest (инертные заглушки, не реальные секреты) |
| `contracts/examples/config/*.json` | AppConfig N=100 и N=10 |
| `contracts/examples/roots/*.json` | RootsResponse: два корня и пустой |
| `contracts/examples/companies/*.json` | CompaniesResponse: Atlas/Nova и пустой |
| `tests/contract/contractlib/synthetic.py` | загрузчик/материализатор/контекстные маркеры/целостность/канонический checksum + команда подготовки |
| `tests/contract/contractlib/fixture_checks.py` | FIX-EX-001/002, FIX-CORPUS-001, FIX-CHK-001 |
| `tests/contract/contractlib/verify.py`, `report.py`, `__init__.py` | интеграция FIX-проверок, поля отчёта, экспорт |
| `tests/contract/verify_contract.py` | строка `Fixtures:` |
| `tests/contract/test_synthetic_corpus.py` | тесты корпуса/примеров/маркеров/portability/негативов |
| `.gitignore` | игнорируется генерируемый `fixtures/synthetic/inventory.json` |
| `README.md` | раздел о корпусе, каноническом checksum и команде подготовки |
| `docs/team/WP-03_SYNTHETIC_HANDOFF.md` | этот handoff |

OAS, `contracts/semantics.md`, control plane и backlog **не изменялись**.

## Версия, seed и контрольная сумма

- `fixture_set = wiseway-synthetic-metadata`, `version = 1.1.1`,
  `seed = wiseway-demo-seed-2031`, `contract_version = 1.0.0`.
- Контрольная сумма — **каноническая JSON-форма**
  (`json.dumps(parse(content), sort_keys=True, separators=(',', ':'), ensure_ascii=False)`),
  поэтому LF- и CRLF-checkout дают одинаковый digest (устраняет блокирующее
  замечание про `core.autocrlf=true`). Метод — `manifest.checksum.canonicalization`.
- `content_hash(corpus.json) = 843659eef9aa39b1ea09e1b7a6cafe91d78eb48ca91abbb17764bc0fc9b5dced`.
- `combined = cef77933500ed97336e2d38d8be670baf448de37ba2d33661bc3afad7e42a7b3`.
- ID детерминированы (без random); `marker_id` выводится из root и полной
  цепочки родителей.

## Что опубликовано

- **Два непересекающихся логических корня:** `root-demo-atlas`
  (`schema-demo-1`, необязательный хвост `level-subcategory` Text/Maps) и
  `root-demo-nova` (`schema-demo-2`, обязательный `level-area` North/South).
  Инвентарь: 162 файла (Atlas 149 / Nova 13), 6 служебных объектов исключены.
- **Компании/проекты:** Atlas, Nova; `Orion_2031`, `Polaris_2030`.
- **Контекстные маркеры (SEM):** `marker_model` объявляет 20 значений и 20
  явных контекстов; загрузчик раскрывает 37 уникальных `marker_id`, каждый
  уникален для `root + цепочка родителей + raw + kind`. Один и тот же `Archive`
  в разных корнях и один и тот же `Reports` под разными родителями получают
  разные ID; повторное использование ID для разной ancestry отсутствует.
  Разный регистр (`Atlas`/`ATLAS`/`atlas`, `Nova`/`NOVA`,
  `Orion_2031`/`orion_2031`, `Polaris_2030`/`polaris_2030`,
  `Reports`/`reports`) — отдельные контексты и ID, каждый имеет файл в корпусе.
- **Широкая ветка:** cohort `atlas-orion-reports-103` — ровно 103 файла
  `Archive/Atlas/Orion_2031/Reports/Atlas-Orion-Report-NNNN.pdf` (> N=100).
- **Четыре структурных отклонения с первым отклонением:**
  `MISSING_REQUIRED_LEVEL` (Nova без Area), `UNEXPECTED_DEPTH` (хвост сверх
  суффикса), `INVALID_LEVEL_VALUE` (недопустимая категория),
  `INVALID_COMPOSITE_SEGMENT` (проект без года); распознанные маркеры — строго
  префикс уровней схемы.
- **Типы/имена:** `.pdf`, `.xlsx`, `.docx`, `.pptx`, `.png`, без расширения,
  нулевой размер, `.env`, `name.`, `archive.tar.gz`, исходный `.TXT`, `.bin`.
- **Контроли и стадии:** `content_only` (probe `zephyr` только в содержимом),
  `old_path` (probe `legacy` в старом пути), lifecycle
  create/change/rename/move/delete; все 8 before/after `SearchItem`
  валидируются в runner.
- **Подготовка LT-03.1b:** `search_inputs` содержит Q-007 AND, Q-008 фраза
  (вставка/перестановка/префикс внутри кавычек/межполевой случай), Q-009 все
  разделители (пробел, дефис, подчёркивание, точка, `/`, `\` через
  `display_path`, буква↔цифра), natural/русский/tie и ranking-входы.
  Канонические `relative_path` всегда `/`; `\` встречается только в
  `display_path`. Списки natural/русской сортировки помечены `ordered=false`
  как неупорядоченные кандидатные входы. Точные запросы/порядок/фасеты — LT-03.1b.

## Формат и ID для следующего leaf

- Инвентарная запись = чистый `SearchItem` (`item_id`, `location`,
  `filename`, `markers`, `extension`, `size_bytes`, `modified_at`,
  `structure_status`, `structure_issue`), валидируется по
  `#/components/schemas/SearchItem`.
- `item_id` стабильны: `file-atlas-*`, `file-nova-*`,
  `file-atlas-orion-report-NNNN`, `service-*`.
- `marker_id` стабильны и контекстно-уникальны:
  `marker-<root_id>-<value_id>-...`; UNRECOGNIZED —
  `marker-<root_id>-...-unrecognized-<level>` (raw=null,
  display=«Не распознано»).
- Корпус раскрывается детерминированно из `marker_model.contexts` и `cohorts`
  (только `{index}` и `index_pad`); никакой поиск/сопоставление не выполняется.

## V-S: точные команды и фактические результаты

Windows (PowerShell), Python 3.14.7, `.venv-contract`:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → exit 0, `RESULT: PASS (26 checks, 0 failures)`,
  `Examples: 127`, `Fixtures: 15 public example(s), 162 corpus file(s) and
  8 lifecycle payload(s) validated`. Добавлены FIX-EX-001 (schema+semantics
  каждого внешнего примера), FIX-EX-002 (все 8 lifecycle before/after),
  FIX-CORPUS-001 (инвентарь/корни/маркеры/отклонения/типы/controls/lifecycle/
  ссылки search_inputs), FIX-CHK-001 (канонический sha256).
- `unittest discover` → `Ran 114 tests ... OK`.
- Исчерпывающий case-sensitive скан: 162 файла + 6 служебных объектов +
  8 lifecycle payloads (176 записей, 693 распознанных маркера) — каждый
  `raw_value` совпадает с ведущими сегментами `relative_path`; нарушений 0.
- `pip check` → `No broken requirements found.`
- `synthetic.py --update-checksums` → детерминированный канонический пересчёт;
  `162 searchable file(s), 6 service object(s)`.
- `git diff --check` → exit 0.

Негативные проверки: schema-дефект примера (нет `csrf_token`) отклоняется;
дубликат `item_id`, пропавший `structure_issue`, утечка служебного объекта,
dangling `marker_context`, дубликат `context_id`, дубликат пути контекста,
дубликат `value_id`, коллизия `marker_id` (гифен-склейка), контекст глубже
объявленной схемы и точечная raw-case мутация одного сегмента пути
отклоняются `integrity_errors` без падения.

## Repair cycle 1 (устранённые блокирующие замечания)

1. **Портируемость checksum.** Сырые байтовые sha256 падали на чистом Windows
   `core.autocrlf=true`. Выбран канонический JSON-hash (см. выше); regression
   LF/CRLF и порядок ключей покрыт тестом
   `test_checksum_is_portable_across_line_endings_and_key_order`.
2. **Контекстные `marker_id` (SEM).** Раньше один `marker_id` переиспользовался
   в разных корнях/цепочках родителей. Введён `marker_model` с явными
   контекстами; ID уникален для root+parents+raw+kind; тест
   `test_marker_id_is_unique_per_root_and_ancestry` (не только dict-key).
3. **Lowercase-варианты.** `atlas`/`reports`/`polaris_2030` не имели файлов;
   добавлены `file-atlas-rawcase-lower` и `file-atlas-rawcase-polaris-lower`,
   тест `test_every_value_marker_is_used_by_a_corpus_file`.
4. **Lifecycle.** Все 8 before/after `SearchItem` теперь валидируются runner-ом
   (`FIX-EX-002`), плюс отдельный тест.
5. **Dangling refs / дубликаты.** `marker_model_errors` и
   `context_reference_errors` сообщают о проблемах без исключения;
   `build_marker_catalog` ловит конфликт идентичностей.
6. **Generated inventory.** `fixtures/synthetic/inventory.json` добавлен в
   `.gitignore`; команда подготовки документирована.
7. **Unordered natural list.** Списки natural/русской сортировки помечены
   `ordered=false` и `note` как кандидатные входы; точный порядок — LT-03.1b.

## Repair cycle 2 (устранённый блокирующий дефект)

- **Дефект:** `file-atlas-rawcase-polaris-lower` имел путь
  `Archive/atlas/polaris_2030/data/polaris-lower.txt`, но объявленный контекст
  заканчивался категорией `Data` (raw `Data`). Сегмент `data` не совпадал с
  распознанным маркером.
- **Исправление:** путь изменён на
  `Archive/atlas/polaris_2030/Data/polaris-lower.txt` (производный
  `display_path` обновляется автоматически); `version` поднята до `1.1.1`,
  checksums пересчитаны.
- **Новая проверка:** `synthetic.path_marker_errors` исчерпывающе (case-sensitive)
  сверяет распознанные VALUE-маркеры с ведущими сегментами `relative_path` для
  всех файлов и lifecycle before/after; это fixture-consistency assertion, а не
  парсер, порождающий эталон. Тест
  `test_every_recognized_marker_matches_its_path_segments` сканирует все 162
  файла и 8 lifecycle payloads.
- **Регрессии:** `test_single_path_raw_case_mutation_is_caught` (точечная
  raw-case мутация пути) и `test_context_deeper_than_declared_schema_is_reported`
  (контекст глубже объявленной схемы; UNRECOGNIZED-терминал оставлен явным
  исключением, текущих нарушений нет).

## Ограничения и явно не выполненное

- **Уровни S:** выполнена только схема/статическая проверка. **M (mock/UI),
  A (реальный API/ФС) и E (E2E) — NOT_RUN.** Файловая безопасность,
  персистентность, гонки и производительность не проверялись и не заявляются;
  физическая ФС-песочница не создавалась.
- Matcher/ranking/readiness/totals/facets не реализуются: корпус только
  предоставляет конечные входы. Точные ожидания Q-004…014/042/043 — LT-03.1b.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.1a (независимая проверка инвентаря,
  контекстных marker ID, корней, канонического checksum, FIX-проверок и
  негативов), затем LT-03.1b (точные поисковые/фасетные ожидания поверх
  `search_inputs`).
- **Блокирующая зависимость:** нет.

# LT-03.1b — точные поисковые/фасетные/auth/error ожидания

Дополнение ниже фиксирует результат leaf LT-03.1b (parent LT-03.1, WP-03,
Epic E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и покрытые требования

- **Цель:** конечный независимый эталон поиска/фасетов/auth/ошибок поверх
  корпуса LT-03.1a, пригодный для mocks и real-регрессии; не matcher.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.1/LT-03.1b; TZ §5/6/12;
  API §2–4/11/12; QA §4/5; MATRIX Q-001…014/042/043 (все параметры);
  `contracts/semantics.md`; OAS `SearchRequest/SearchResponse/FacetRequest/
  FacetResponse/SearchItem/Marker/ErrorResponse`.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/search_expectations.json` | новый литеральный эталон: 51 search, 6 facet, 3 auth, 14 error, 3 race, 5 lifecycle, 3 format, 1 sort_profile + coverage Q-001…014/042/043 |
| `fixtures/synthetic/corpus.json` | исправления/дополнения корпуса (см. ниже), version 1.2.0 |
| `fixtures/synthetic/manifest.json` | version 1.2.0, секция `fixtures`, 17 новых привязанных examples, канонические checksums |
| `tests/contract/contractlib/search_expectations.py` | загрузчик/материализатор/валидатор + `--write-examples`; per-operation error-code check |
| `tests/contract/contractlib/fixture_checks.py` | FIX-SRCH-001/002, `checksum.fixtures` |
| `tests/contract/contractlib/synthetic.py` | `compute_checksums` учитывает `fixtures`; `path_marker_errors` требует VALUE-only маркеры и path prefix |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | поля/экспорт/строка отчёта |
| `tests/contract/test_search_expectations.py` | 45 тестов: схемы/counts/ID/coverage/генерация/негативные мутации |
| `contracts/examples/search/*.json`, `contracts/examples/errors/*.json` | 17 сгенерированных публичных payloads |
| `tests/contract/test_synthetic_corpus.py` | 162→164 и обновлённый отчёт runner |
| `README.md` | раздел LT-03.1b и команда генерации |

OAS, `contracts/semantics.md`, control plane, backlog и backend/UI **не
изменялись**.

## Что именно зафиксировано

- **IDLE:** оба корня (Atlas 151 / Nova 13), `total=null`, `items=[]`,
  первый level-section facet; точный ноль `zzzznothing` → `options=[]`.
- **L+3:** N10 `nova` → total 13, returned 10, `limited=true`; N100
  `"orion report"` → total 103, returned 100 (0001..0100).
- **AND/регистр:** `atlas reports` = `ATLAS REPORTS` = 6 файлов; цепочка
  markers+text.
- **Фраза:** `"atlas main"` → `Atlas-Main.pdf`, `Atlas-Main-Metrics.pdf`;
  вставка/перестановка/Maintenance/межполевой случай отрицательны; `met`
  снаружи — отдельное обязательное условие (25).
- **Границы токенов:** пробел, дефис, подчёркивание, точка, `/`, `\`,
  буква↔цифра положительны; внутренняя подстрока, буква перед `met`, опечатка
  отрицательны. Slash/backslash — только через `display_path`.
- **Ранжирование:** ручные score 10/5/2 (`met`), 10 (`atlas` full), 5
  (`atla` prefix), 10/6 (`nova`), 20 (фраза), 4 (фраза через уровни), 25
  (фраза+внешний prefix); повтор токена и дубль имени в `display_path` не
  добавляют.
- **Tie-break:** natural path (`item-2` < `item-10` < `Item.pdf`),
  raw path (`NOTE.pdf` < `Note.pdf`); item_id — отдельный stand-alone
  `sort_profiles[0]` (два логических `SearchItem` с одинаковым display sort key
  и разными ID; ожидаемый порядок alpha < beta). Это comparator-профиль, не
  физический инвентарь; backend-алгоритм не реализуется.
- **Сортировки:** NAME/SIZE/MODIFIED_AT/PATH ASC и DESC.
- **Raw-case/tail/Area/UNRECOGNIZED:** отдельные marker_id (`ATLAS`/`Atlas`/
  `atlas`), optional Text/Maps, Nova Area North/South, терминал
  UNRECOGNIZED=1 последним; четыре issue-типа с первым отклонением.
- **Freshness:** `constants.freshness_profiles` CURRENT/UPDATING/STALE; при
  UPDATING/STALE предыдущее завершённое поколение остаётся доступным
  (`SRCH-Q011-FRESHNESS-UPDATING`, `SRCH-Q003-FRESHNESS-STALE` дают те же
  items/total, что CURRENT-сценарий).
- **Q-014:** content-only/old-path/service-папки → 0, текущий контроль
  находится, zero-size/без расширения/.TXT индексируются; lifecycle
  create/change/rename/move/delete.
- **Auth/errors:** точные 401 `UNAUTHENTICATED`/`LOGIN_FAILED`, 204 logout,
  503 `SEARCH_UNAVAILABLE`, 500 `INTERNAL_ERROR`, 400 `INVALID_QUERY`,
  422 `VALIDATION_ERROR`/`INVALID_MARKER_SELECTION`, 409
  `SCHEMA_VERSION_CHANGED`/`ROOT_NOT_READY`, 429 `RATE_LIMITED`;
  `error.request_id` совпадает с заголовком, `operation_id=null`. 403
  привязан к операции: `CSRF_FAILED` — `logout` (WriteForbidden, реальная
  мутация, неверный X-CSRF-Token), `FORBIDDEN` — `login` с запрещённым Origin.
  Код проверяется против **канонической response-схемы конкретной операции**,
  а не глобальной таблицы HTTP/код.
- **Races:** последний `request_state_id` scope побеждает; разрешённый retry
  после ошибки получает новый ID.
- **Q-042:** литеральные `0 B`/`1.5 KB`/`4.1 KB`/`1 MB`…, дата
  `10.05.2031 12:30` в Europe/Moscow, `display_path` одной строкой.

## Исправления корпуса (все затронутые ожидания обновлены, не скрытое исключение)

1. **UNRECOGNIZED-терминал.** Три issue-файла (`invalid-value`,
   `invalid-composite`, `missing-area`) сохранены на **распознанных VALUE-
   родителях** (baseline-контексты), как требует `SearchItem.markers`. Каталожные
   UNRECOGNIZED-контексты (`...-unrecognized-category/project/area`) остаются в
   `marker_catalog` отдельно — для `selected_markers`/фасетов; они намеренно не
   привязаны к item. Связь «первое отклонение → терминальная опция» задана
   литерально в `facet.expected.unrecognized_sources` (item, code, level), без
   парсера. `path_marker_errors` теперь строго требует VALUE-only маркеры и
   prefix-совпадение с сегментами пути.
2. **Q-007/Q-008 prepared inputs.** `q007_and.matching_item_ids` включал только
   `q007-both`, хотя под `Reports/` с `Atlas` в имени подходят ещё пять q008-
   файлов; `q008_phrase` не включал `mixed`, который тоже содержит соседние
   `Atlas Main`. Оба списка приведены к семантике filename+display_path.
3. **Raw tie.** Добавлена минимальная пара `file-atlas-tie-raw-note-upper`
   (`NOTE.pdf`) и `file-atlas-tie-raw-note-lower` (`Note.pdf`) — равный natural
   path, разный raw path; это делает второе звено tie-break проверяемым.
4. **MODIFIED_AT.** `q009-space` (09:00Z) и `q009-letter-digit` (10:00Z)
   получили отличимые `modified_at`, чтобы направление ручной сортировки
   даты было проверяемым.
5. Baseline VALUE-контексты (`atlas-archive-atlas`,
   `atlas-archive-atlas-orion`, `nova-archive-nova-polaris`) сохранены —
   они нужны распознанным родителям issue-файлов.

Итог: корпус 164 файла (Atlas 151 / Nova 13), 6 service objects, 37 marker_id,
8 lifecycle payloads, fixture version `1.2.0`.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\search_expectations.py --write-examples
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (28 checks, 0 failures)`,
  `Examples: 127`, `Fixtures: 32 public example(s), 164 corpus file(s) and
  8 lifecycle payload(s) validated`,
  `Search expectations: 51 search, 6 facet, 14 error, 3 race, 3 format`.
  FIX-SRCH-001/002 — PASS.
- `unittest discover` → `Ran 159 tests ... OK`.
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-SRCH-002).

Негативные self-тесты: испорченный `returned_count`/`total`, обратный порядок
при разных score, неизвестный `item_id`, count=0 во фасете, пустая coverage,
неизвестный `error.code`, разорванная цепочка маркеров, пустой `reason`,
**код ошибки, не объявленный канонической response-схемой операции**
(`CSRF_FAILED` на `searchFiles`), **UNRECOGNIZED-маркер внутри
`SearchItem.markers`** и обратный порядок stand-alone tie-профиля —
отклоняются `expectation_errors`/`path_marker_errors`.

## Ограничения и явно не выполненное

- Это **S**-уровень: схема/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Физическая
  безопасность, персистентность, гонки и производительность не проверялись.
- `search_expectations.py` — материализатор по литеральным ID; он не содержит
  matcher/ranking/facet-вычислений. Значения `item_ids`/`score`/`count`
  получены ручным разбором корпуса и зафиксированы в `reason` каждого сценария.
- `error.operation_id` во всех auth/search-ошибках равен null; не-null случай
  (registered recovery) относится к QUEUE/FILE/AUD и покрывается LT-03.5b.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push
  worker не выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.1b — независимая сверка конечных ID,
  порядка, counts и фасетов по `reason` и корпусу, а также негативных мутаций.
- **Блокирующая зависимость:** нет.

# LT-03.2a — эталоны правил, целей и резолвера

Дополнение фиксирует результат leaf LT-03.2a (parent LT-03.2, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечный независимый эталон `rule-input => target/name/reason` и
  оракулы резолвера целей для будущих simulation/sorting fixtures (LT-03.2b+);
  matcher не реализуется.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.2/LT-03.2a; D-03/D-06; TZ
  DICT-01…07; API §5/6; QA §4; MATRIX Q-015/Q-018/Q-044; OAS
  `Rule`/`TargetDirectory`/`TargetReference`/`Dictionary`/`DictionaryDraft`/
  `DictionaryVersion`/`RuleSet`/`RuleReference`/`PlanRow`/`ReplaceDictionaryDraft`
  и response-схемы `resolveTargetDirectory`/`replaceDictionaryDraft`.

## Изменённые файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/rule_expectations.json` | новый эталон: 2 компании, 3 словаря (2 Atlas + 1 Nova), 16 версий (3 published + 13 сценарных), 13 rule set, 9 целей, 24 источника, 26 rule, 8 target, 17 invalid-rule сценариев, coverage Q-015/018/044 |
| `contracts/examples/targets/*.json` | 3 публичных `TargetDirectory` |
| `contracts/examples/dictionaries/*.json` | 3 `Dictionary`, 3 `DictionaryVersion`, 2 `RuleSet`, 4 `PlanRow` |
| `contracts/examples/errors/error-invalid-target.json`, `error-path-outside-root.json` | 2 публичных `ErrorResponse` |
| `tests/contract/contractlib/rule_expectations.py` | загрузчик/материализатор/валидатор + `--write-examples` |
| `tests/contract/contractlib/fixture_checks.py` | FIX-RULE-001/002 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_rule_expectations.py` | 36 тестов: структура, покрытие, role/история, негативные мутации |
| `tests/contract/test_synthetic_corpus.py` | 32→49 публичных примеров и FIX-RULE-счётчики |
| `fixtures/synthetic/manifest.json` | fixture `rule-expectations`, 17 привязанных examples, пересчитанные канонические checksums; version корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.2a и команда генерации |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI **не
изменялись**.

## Что именно зафиксировано

- **Компании/акторы:** `company-demo-atlas`/`company-demo-nova` с
  `incoming_source_ids`, сверенными с корпусом; точные акторы auth fixtures
  `user-demo-worker-1`, `user-demo-worker-2`, `user-demo-admin-1`.
- **Справочники/полный RuleSet:** Atlas — `dictionary-atlas-general` +
  `dictionary-atlas-invoices` (два словаря одной компании), Nova —
  `dictionary-nova-general`; опубликованные rule set содержат все активные
  версии компании, members отсортированы по `dictionary_id`; каждая ссылка
  правила разрешается в полное определение (нет undefined refs).
- **role/history:** каждая версия помечена `role`. `published` — живая история
  словаря, единственная, что считает публичный `Dictionary.versions_count`;
  `scenario` — изолированный тестовый универсум для будущих simulation
  fixtures, на который ссылаются только сценарные rule set. Опубликованный
  rule set не может ссылаться на сценарную версию; сценарные версии не входят
  в основную timeline.
- **Суффиксы:** `archive.tar.gz` → `Archive.gz`; `.env` → `EnvFile`; `README` →
  `Readme`; `name.` → `Named`; `invoice.TXT` → `Invoice.TXT` (регистр сохранён);
  `report.v2.pdf` + точечная основа → `Final.Report.pdf` (только последний
  суффикс).
- **BASENAME/RELATIVE_PATH:** правило BASENAME не подставляет путь; при
  `*orion*` матчится только RELATIVE_PATH.
- **Whole-field/маски:** `invoice` совпадает только с целым полем, подстроке
  нужны `*`; `*` — ноль/много и пересекает слеш; `?` — ровно один.
  Cross-slash положительный: `Archive*Reports/*` матчит полный относительный
  путь `Archive/Atlas/Orion_2031/Reports/summary.pdf`, т.к. маска применяется
  ко всему полю включая basename; trailing-only `Archive*Reports` — отдельный
  отрицательный контроль (`NO_SCENARIO`).
- **Слеши/регистр:** маска с `\` совпадает с каноническим `/`; casefold
  регистронезависим, но без NFC/NFKC (decomposed `e`+U+0301 не совпадает).
- **Приоритет:** 1 и 1000; меньший выигрывает; больший не перебивает меньший.
- **Одинаковый приоритет:** одинаковая цель не конфликтует, атрибуция
  стабильна по `dictionary_id` → `rule_id`; разные цели дают `RULE_CONFLICT`
  без выбранного правила и без цели.
- **Резолвер:** разрешённые цели Atlas/Nova; `NoSuchDir` → 422
  `INVALID_TARGET`; `DEMO:/OtherSandbox/...` → 422 `PATH_OUTSIDE_ROOT`;
  пустой сегмент → 422 `VALIDATION_ERROR`; `C:/Windows/System32` → 422
  `INVALID_TARGET`; чужой компании → 422 `INVALID_TARGET`.
- **Invalid rules:** `**`, пустая/длинная маска, приоритет 0/1001, пустая/
  длинная/слэш/бэкслэш/control основа, неизвестный `match_field`, отсутствие
  `target` — схемно отклоняются (`schema_rejected=true`); regex/скрытый OR/
  escape/недопустимая или чужая цель — доменные отклонения
  (`schema_rejected=false`), привязанные к response-схеме
  `replaceDictionaryDraft`.
- **Roundtrip:** каждый `Rule` материализуется с 6 полями и nested `target`,
  валидируется схемой и сохраняется при JSON dump/load.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\rule_expectations.py --write-examples
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (30 checks, 0 failures)`, `Fixtures: 49`,
  `Rule expectations: 26 rule, 8 target, 17 invalid-rule`; FIX-RULE-001/002 —
  PASS.
- `unittest discover` → `Ran 195 tests ... OK` (было 191; добавлено 4: role/history,
  cross-slash negative, incoming_source_ids, scenario-in-published-rule-set).
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-RULE-002).
- Негативные self-тесты: undefined rule ref, ссылка вне rule set, selected не
  из matched, конфликт с одним совпадением, равный приоритет с разными целями,
  несовпадение stem+suffix/basename, цель вне allowlist, код не из response
  схемы операции, пустой reason, дубликат `rule_id`, пропавшее покрытие,
  неверная классификация `schema_rejected`, сценарная версия в published
  rule set, неизвестный `role`, расхождение `incoming_source_ids` — отклоняются
  `expectation_errors`/`schema_rejection_errors`.

## Repair cycle 1 (устранённые блокирующие замечания)

1. **Неверная finite-пара cross-slash.** Маска `Archive*Reports` не могла
   матчить полный путь `Archive/Atlas/Orion_2031/Reports/summary.pdf`, т.к.
   поле — весь относительный путь включая basename. Исправлено на
   `Archive*Reports/*` в `version-atlas-star-cross-slash-v1`; обновлены
   `parameters`/`reason`, сгенерированные примеры и checksums. Добавлен
   отдельный отрицательный контроль `RULE-Q015-STAR-CROSS-SLASH-TRAILING-NO-MATCH`
   (`version-atlas-star-cross-slash-neg-v1`, `rule-set-atlas-star-cross-slash-neg`)
   для старой trailing-only маски. Matcher не реализован: значения остаются
   литеральными.
2. **История словаря и сценарный универсум.** Публичный
   `Dictionary.versions_count` теперь считает только `role="published"`;
   сценарные версии сохранены для simulation fixtures, но исключены из живой
   timeline и не могут входить в опубликованный rule set. Добавлен
   `published_versions(...)` и тест соответствия публичной истории экспорту.
3. **Метаданные компаний.** `incoming_source_id` заменён на
   `incoming_source_ids`, сверенный с корпусом; добавлена проверка и
   негативный тест.

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Файловая
  безопасность, персистентность и гонки не проверялись.
- Жизненный цикл (simulation/publish/revision/ack/TTL/restore) — LT-03.2b; здесь
  только неизменяемые определения и оракулы.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## ID-модель для следующего leaf (LT-03.2b)

- Компании: `company-demo-atlas`, `company-demo-nova`.
- Словари: `dictionary-atlas-general`, `dictionary-atlas-invoices`,
  `dictionary-nova-general`; версии `version-<dict>-vN`; rule set
  `rule-set-atlas-published`, `rule-set-nova-published` (+ сценарные).
- Правила: `rule-<dict>-<case>`; цели `target-<company>-<dir>`; источники
  `src-...`; сценарии `RULE-Q0xx-...`, `TARGET-Q044-...`,
  `RULE-INVALID-...`.
- Каждый независимый вариант обязан иметь собственный version/rule_set ID и
  ссылаться на полные определения.

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.2a (независимая сверка литеральных
  ожиданий/целей/суффиксов, полного RuleSet, классификации invalid rules и
  негативных мутаций), затем LT-03.2b (simulation/publish lifecycle).
- **Блокирующая зависимость:** нет.

# LT-03.2b — эталон жизненного цикла справочника

Дополнение фиксирует результат leaf LT-03.2b (parent LT-03.2, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечный, внутренне связанный эталон draft/simulation/publication/
  history/restore двух актёров поверх неизменяемых определений LT-03.2a; runtime
  домен (matcher/резолвер/подсчёт) не реализуется.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.2/LT-03.2b; D-03/D-06; TZ
  DICT-08…12; API §2 (идемпотентность) и §6; QA §4; MATRIX Q-016…021/029; OAS
  createDictionary/replaceDictionaryDraft/restoreDictionaryDraft/
  createDictionarySimulation/getSimulation/publishDictionary/listDictionaryVersions/
  getDictionaryVersion и схемы Dictionary/DictionaryDraft/DictionaryVersion/
  RuleSet/RuleReference/PlanRow/Simulation/PlanCounts/PublishedDictionaryResponse/
  ErrorResponse.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/dictionary_lifecycle.json` | новый эталон: 19 timeline, 16 failure, 1 replay, 7 simulation pages, 3 publishes, 14 states, 5 rule sets, 5 ready sets, 5 lifecycle versions, coverage Q-016…021/029 |
| `contracts/examples/dictionaries/*.json` | 14 публичных Dictionary/Version/RuleSet/PublishedDictionaryResponse примеров |
| `contracts/examples/simulations/*.json` | 6 публичных Simulation (полный READY page1/page2, empty, conflict, same-target, restored) |
| `contracts/examples/errors/*.json` | 6 новых ErrorResponse (draft/name/stale/ack/conflict/idempotency) |
| `tests/contract/contractlib/dictionary_lifecycle.py` | загрузчик/материализатор/валидатор + `--write-examples`; переиспользует `rule_expectations` для определений, не дублирует matcher |
| `tests/contract/contractlib/fixture_checks.py` | FIX-DLC-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_dictionary_lifecycle.py` | 48 тестов: структура/покрытие/переходы/audit expectations/негативные мутации |
| `tests/contract/test_synthetic_corpus.py` | 49→77 публичных примеров и FIX-DLC-счётчики |
| `fixtures/synthetic/manifest.json` | fixture `dictionary-lifecycle`, 28 привязанных examples, пересчитанные канонические checksums; version корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.2b и команда генерации |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI и
`corpus.json`/`rule_expectations.json` **не изменялись**. Корпус `1.2.0`.

## Что именно зафиксировано

- **Timeline:** create пустого черновика revision 0; save 0→1 и 1→2; полный
  READY-тест; принятая публикация v2; поздняя публикация второго справочника
  Atlas; restore v1 → simulate → publish v3 с `restored_from_version_id=v1`;
  ручная правка после restore очищает `based_on_version_id`; чтение истории
  v3/v2/v1.
- **Stale shared revision:** второй актор с ожидаемой revision 1 получает 409
  `DRAFT_VERSION_CONFLICT` без записи; первая версия не перезаписана.
- **Имя:** конфликт после trim+casefold внутри компании (409
  `DICTIONARY_NAME_CONFLICT`); то же имя в другой компании разрешено (201).
- **Simulation:** кандидат заменяет только свою версию в полном RuleSet
  (`rule-set-atlas-v2`: general v2 + invoices v1); охвачены все READY, включая
  скрытые/отфильтрованные и элемент, покрытый другим справочником; явные
  membership/total/PlanCounts/rows/pages; пустой READY даёт `EMPTY_READY_SET`.
- **Конфликты/цели:** равный приоритет с разными целями → `RULE_CONFLICT` и 409
  при publish; одинаковая итоговая цель конфликтом не является (stable
  dictionary_id → rule_id); занятая цель → `REQUIRES_DECISION`/`TARGET_OCCUPIED`
  и **не** блокирует публикацию.
- **NO_SCENARIO:** ack=false → 409 `NO_SCENARIO_ACK_REQUIRED`; ack=true с
  комментарием 1…500 → 201; пустой и 501-символьный комментарий — 422
  `VALIDATION_ERROR` (схемное отклонение request).
- **Устаревание:** отдельные сценарии stale draft (409
  `DRAFT_VERSION_CONFLICT`), изменённый участник RuleSet, изменённый READY-набор
  и истёкший TTL (409 `STALE_SIMULATION`).
- **Публикация/history:** принятая публикация отдаёт полный активный RuleSet,
  неизменяемую версию и историю; `batch_bindings` описывает ожидаемое
  связывание будущей партии (партии ещё нет) и требует immutable published
  версии; поздняя правка/публикация историю не меняет.
- **Идемпотентность:** replay того же UUID/пользователя/тела возвращает ту же
  версию до проверки TTL; изменённое тело тем же пользователем — 409
  `IDEMPOTENCY_KEY_REUSED`; другой актор с тем же UUID — новая операция (ключ
  scoped по user), не конфликт ключа, и оценивается по текущим условиям
  (устаревший тест → 409 `STALE_SIMULATION`).
- **Изолированные состояния:** conflict/same-target используют собственные
  состояния справочника с ревизиями 101/102 и меткой `universe`, без ссылки на
  живую revision 2; публикация invoices v2 проходит через отдельный save
  (revision 1→2, точные v2-правила), base RuleSet до публикации содержит
  предыдущую active invoices v1, а публикация фиксирует v2.
- **Crosslinks:** каждый успешный шаг timeline структурно связан со своим
  состоянием/симуляцией/публикацией: ревизии, `expected_draft_revision`,
  `candidate_version_id`, base RuleSet (предыдущая active), комментарий
  запроса == комментарий версии, draft.rules после публикации == правила
  версии.
- **Ссылки:** все version/rule/target refs разрешаются в полные определения;
  сценарные version/rule-set ID отделены от опубликованной истории; `history`
  считает только собственные published версии словаря.
- **Failures:** у каждого точный operation/request/preconditions/HTTP/код,
  `mutates=false`, `before_state == after_state`; код проверяется по
  канонической response-схеме конкретной операции.
- **Audit expectations:** `audit_expectations` фиксирует ожидаемые
  `AuditAction`/`AuditResult` каждого успешного сценария для LT-03.5b с
  `evidence=false`; это ожидание, а не записанное audit evidence.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\dictionary_lifecycle.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (33 checks, 0 failures)`, `Fixtures: 77`,
  `Dictionary lifecycle: 19 timeline, 16 failure, 1 replay, 7 simulation page(s)`;
  FIX-DLC-001/002/003 — PASS.
- `unittest discover` → `Ran 243 tests ... OK` (было 195; добавлено 48).
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-DLC-003). `--update-checksums` не меняет
  пересчитанный manifest.
- Негативные self-тесты: undefined rule ref, total не покрывает READY,
  PlanCounts не сходятся с total, пропавший `EMPTY_READY_SET`, конфликт с одним
  совпадением, failure с мутацией, чужой код ошибки для операции, история не
  растёт на новую версию, `restored_from` из чужого словаря, replay с другим
  телом, сценарная версия в published rule set, пропавшее покрытие,
  неверная классификация `schema_rejected`, а также crosslink-дефекты:
  комментарий запроса ≠ комментарий версии, draft.rules ≠ правила версии,
  base RuleSet уже привязан к публикуемой версии, `draft_revision` симуляции ≠
  before_state, `candidate_version_id` чужого словаря, `universe` симуляции ≠
  before_state, save без инкремента ревизии, restore с чужим `based_on`.

## Repair cycle 1 (устранённые блокирующие замечания)

1. **User-scoped idempotency.** `publish-idempotency-other-user` больше не
   объявляет 409 `IDEMPOTENCY_KEY_REUSED`: другой актор с тем же UUID — новая
   операция (ключ scoped по user), которая оценивается по текущим условиям.
   Заменено на `publish-other-user-new-operation-stale` → 409
   `STALE_SIMULATION` (тест реально устарел после поздней публикации invoices
   v2). Убрано неверное утверждение из README/handoff.
2. **Invoices v2 flow.** Добавлен `state-atlas-invoices-draft-v2` (revision 1→2,
   точные 4 правила v2) и шаг `save-atlas-invoices-v2`; симуляция
   `simulation-atlas-invoices-v2` использует base RuleSet `rule-set-atlas-v2`
   (предыдущая active invoices v1), а публикация фиксирует v2
   (`rule-set-atlas-v2-invoices-v2`). `candidate_version_id` задан явно.
3. **Комментарии публикаций.** Комментарии версий v2/v3/invoices v2 приведены
   к комментариям соответствующих запросов; добавлена проверка для всех
   успешных publish: `request.comment == version.comment` и
   `after_state.draft.rules == version.rules`.
4. **Изолированные conflict/same-target.** Добавлены собственные состояния
   `state-atlas-general-scenario-conflict` (revision 101) и
   `state-atlas-general-scenario-same-target` (revision 102) с фактическими
   candidate-правилами, меткой `universe`, без живой истории; timeline-шаги и
   failure `publish-conflict-blocked` переведены на них. Добавлены crosslink-
   проверки для всех успешных шагов timeline (ревизии, base RuleSet =
   предыдущая active, candidate version, комментарий, draft.rules), а также
   негативные тесты на эти crosslinks.

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Файловая
  безопасность, персистентность, TTL-часы и гонки не проверялись.
- Runtime домен (matcher/резолвер/подсчёты/revision bump) не реализуется:
  значения объявлены литерально и сверяются между собой.
- Ожидаемые action/audit ID зафиксированы для LT-03.5b, но не являются
  audit evidence. Batch runtime отсутствует; связывание описано.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.2b (независимая сверка timeline,
  membership/counts, конфликтов/целей, stale-сценариев, restore/идемпотентности
  и негативных мутаций), затем LT-03.3a (очередь/readiness/snapshot).
- **Блокирующая зависимость:** нет.
