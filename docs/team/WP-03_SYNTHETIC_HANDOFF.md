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

# LT-03.3a — эталон очереди, readiness и снимков выбора

Дополнение фиксирует результат leaf LT-03.3a (parent LT-03.3, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечный независимый эталон очереди компании, готовности входящих
  и неизменяемого снимка выбора для будущих preview/batch leaf-ов; matcher,
  readiness-детектор и selection-алгоритм не реализуются.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.3/LT-03.3a; D-03/D-06; API §7/8
  (selection ownership + preflight); TZ QUEUE-01/02/03/10; QA §4; MATRIX
  Q-022/023/024/025/026; OAS `QueueItem`/`QueueResponse`/`QueueFilters`/
  `SelectionRequest`/`SelectionSnapshot`/`ErrorResponse`; `contracts/semantics.md`.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/queue_selections.json` | новый эталон: 4 профиля (0/120/1001 READY + изолированный stability), 8 запросов, 5 readiness-наблюдений, 3 selection, 7 error, 4 ownership, 3 sequence, 10 invalid-request, 16 links, 12 mutations, coverage Q-022…026 |
| `contracts/examples/sorting/*.json` | 13 публичных QueueResponse/SelectionRequest/SelectionSnapshot |
| `contracts/examples/errors/error-empty-selection.json` и др. | 7 публичных ErrorResponse |
| `tests/contract/contractlib/queue_selections.py` | generic declarative loader/checker + `--write-examples`; переиспользует `semantic.validate_fixture`/`queue_response_errors`, `rule_expectations` для RuleSet identity |
| `tests/contract/contractlib/fixture_checks.py` | FIX-QUEUE-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_queue_selections.py` | тесты: структура/схемы/counts/membership/readiness/TTL/ownership/links/негативные мутации |
| `tests/contract/test_synthetic_corpus.py` | 77→97 публичных примеров и FIX-QUEUE-счётчики |
| `fixtures/synthetic/manifest.json` | fixture `queue-selections`, 20 привязанных examples, пересчитанные канонические checksums; version корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.3a и команда генерации |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI и
`corpus.json`/`rule_expectations.json`/`dictionary_lifecycle.json` **не
изменялись**. Корпус `1.2.0`.

## Что именно зафиксировано

- **Профили READY 0/120/1001.** `status_counts` покрывают все семь состояний;
  `counters.ready/processing/attention` и `attention = REQUIRES_DECISION +
  RECOVERY_REQUIRED`; `matching_count`/`eligible_count` различаются для READY
  (120/120) и default-active (130/121); страница ≤100 при общем 120;
  `MISSING` отсутствует в default-active и появляется только по явному фильтру.
- **selectable.** `true` только для стабильного READY или стабильного
  REQUIRES_DECISION без active claim. Стабильность — не поле `QueueItem`
  (схема закрыта), а явная метадата группы bundle; `queue_response_errors`
  проверяет только DTO-инвариант (`selectable=true` запрещён вне
  READY/REQUIRES_DECISION и при active claim), а `membership_errors` сверяет
  `selectable` с явной `stable`. Изолированный профиль
  `QUEUE-Q022-DECISION-STABILITY` добавляет нестабильный REQUIRES_DECISION без
  claim с `selectable=false`; claimed REQUIRES_DECISION, PROCESSING,
  RECOVERY_REQUIRED, MISSING, DISCOVERED, WAITING_READY — `false`.
- **readiness.** Два равных size/mtime ≥5 с без unfinished → READY; изменение и
  переименование → WAITING_READY с новой содержательной ревизией; unfinished
  остаётся WAITING_READY; claim → PROCESSING без смены содержательной ревизии.
  Это конечная последовательность ожиданий, не физическое доказательство.
- **selection.** EXPLICIT одного/нескольких (включая off-page `0101`/`0120`) и
  ALL_MATCHING 120: literal membership, `selected_count`, `queue_generation`,
  TTL 300 с; late arrival и смена фильтра снимок не меняют. ID снимка
  `selection-atlas-allmatching-120` уникален для bundle и не совпадает с
  одноимённым встроенным примером OAS (тот не изменялся).
- **Ошибки.** 422 `EMPTY_SELECTION`, 422 `BATCH_LIMIT_EXCEEDED` (без усечения),
  409 `SELECTION_CHANGED` до создания, 403 `FORBIDDEN`, 409 `SELECTION_EXPIRED`
  на реальных `createSortingPreview`/`createSortingBatch`, 404 `NOT_FOUND`.
  Коды сверяются с канонической response-схемой конкретной операции.
- **Schema.** Queue/SelectionRequest/SelectionSnapshot/Error payloads валидны;
  запросы без компании, пустой/1001-элементный EXPLICIT, неизвестный режим и
  лишние поля помечены `schema_rejected=true`; invalid refs/dups/company shapes
  проверяются generic links/mutations.
- **RuleSet.** `rule-set-atlas-published` с members general v1 + invoices v1
  совпадает с принятой идентичностью LT-03.2b — LT-03.3b обязан её
  переиспользовать.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\queue_selections.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (36 checks, 0 failures)`, `Fixtures: 97`,
  `Queue expectations: 4 profile(s), 8 query(ies), 3 selection, 7 error,
  5 readiness, 4 ownership scenario(s)`; FIX-QUEUE-001/002/003 — PASS.
- `unittest discover` → `Ran 287 tests ... OK` (было 243; добавлено 44).
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-QUEUE-003). `--update-checksums` не меняет
  пересчитанный manifest.
- Негативные self-тесты: неверный `status_counts`/`attention`, страница не
  равная лимиту, MISSING в default-очереди, несовпадение `selected_count`,
  чужая компания, неизвестный member, несовпадение ревизии, короткий интервал
  и unfinished-маркер readiness, drift `queue_generation`, drift RuleSet,
  `selectable=true` у нестабильного REQUIRES_DECISION и пропавшая явная
  `stable`-метадата — отклоняются `expectation_errors`/`mutation_errors`.

## ID-модель для следующего leaf (LT-03.3b)

- Профили: `QUEUE-Q022-READY-120`, `QUEUE-Q024-READY-0`,
  `QUEUE-Q024-READY-1001`, `QUEUE-Q022-DECISION-STABILITY`; запросы
  `Q-Q024-READY-PAGE1`, `Q-Q022-ALL-ACTIVE`, `Q-Q022-MISSING-EXPLICIT`,
  `Q-Q022-QUERY-TEXT`, `Q-Q024-READY-EMPTY`, `Q-Q022-ALL-ACTIVE-0`,
  `Q-Q024-READY-LIMIT-PAGE1`, `Q-Q022-STABILITY-ACTIVE`.
- Снимки: `selection-atlas-explicit-one` (1), `selection-atlas-explicit-multiple`
  (3, off-page `queue-atlas-ready-0101`/`0120`),
  `selection-atlas-allmatching-120` (120).
- Item IDs READY-120: `queue-atlas-ready-0001…0120`; READY-1001:
  `queue-atlas-limit-0001…1001`; `queue_generation`:
  `queue-generation-atlas-120`/`-0`/`-1001`.
- Ошибки: `SEL-ERR-EMPTY`, `SEL-ERR-LIMIT`, `SEL-ERR-CHANGED`,
  `SEL-ERR-FORBIDDEN`, `SEL-ERR-EXPIRED-PREVIEW`, `SEL-ERR-EXPIRED-BATCH`,
  `SEL-ERR-NOT-FOUND`.
- **RuleSet для preview:** `rule-set-atlas-published` (general v1 + invoices v1).

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Физическая
  готовность, персистентность, TTL-часы и гонки не проверялись.
- Matcher/readiness/selection/preflight не реализуются: значения объявлены
  литерально и сверяются между собой; `query_text` — литеральный список.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.3a (независимая сверка counts,
  membership, readiness-переходов, ownership/TTL и негативных мутаций), затем
  LT-03.3b (preview: Prediction/CollisionDetails и DIRECT/PREVIEWED preflight).
- **Блокирующая зависимость:** нет.

# LT-03.3b — эталон preview и DIRECT/PREVIEWED preflight

Дополнение фиксирует результат leaf LT-03.3b (parent LT-03.3, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечный независимый эталон не мутирующего preview и проверок
  `DIRECT`/`PREVIEWED` до принятия партии поверх неизменяемых снимков LT-03.3a
  и полных определений LT-03.2a/2b; matcher, priority resolver, target-name
  derivation и preflight-алгоритм не реализуются.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.3/LT-03.3b; D-03/D-06; API §7/8
  (таблица preflight-ошибок); TZ QUEUE-04/05/06, DICT-12; QA §4; MATRIX
  Q-023/026/027; OAS `Preview`/`PlanRow`/`Prediction`/`CollisionDetails`/
  `BatchCreateRequest`/`ErrorResponse`; `contracts/semantics.md`.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/preview_preflight.json` | новый эталон: 6 preview-групп (120 в двух страницах, one, multiple, isolated hetero, conflict, Nova-foreign), 18 preflight-сценариев (3 принятых, 15 отказов), 4 post-acceptance исхода, 8 error, 9 invalid-request, 8 links, 17 mutations, coverage Q-023/026/027 |
| `contracts/examples/sorting/preview-atlas-*.json` | 5 публичных Preview |
| `contracts/examples/errors/error-batch-*.json`, `error-preview-*.json` | 8 публичных ErrorResponse |
| `tests/contract/contractlib/preview_preflight.py` | declarative loader/checker + `--write-examples`; переиспользует `queue_selections` (снимки) и `rule_expectations` (RuleSet/version/rule/target) |
| `tests/contract/contractlib/fixture_checks.py` | FIX-PREVIEW-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_preview_preflight.py` | 55 тестов: структура/схемы/prediction/collision/binding/preflight/негативные мутации |
| `tests/contract/test_synthetic_corpus.py` | 110 публичных примеров, FIX-PREVIEW-счётчики |
| `fixtures/synthetic/manifest.json` | fixture `preview-preflight`, 13 привязанных examples, пересчитанные канонические checksums; версия корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.3b и команда генерации |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI и
`corpus.json`/`rule_expectations.json`/`dictionary_lifecycle.json`/
`queue_selections.json` **не изменялись**. Корпус `1.2.0`.

## Что именно зафиксировано

- **Привязка к снимкам.** `selection-atlas-allmatching-120` (120),
  `selection-atlas-explicit-one` (1) и `selection-atlas-explicit-multiple` (3,
  off-page `0101`/`0120`) материализуются из `queue_selections.json`; страницы
  preview покрывают ровно их membership с теми же item_id/revision/source, а
  `total` равен `selected_count`. `expires_at` preview не позже снимка.
- **Изолированные наборы.** `selection-preview-atlas-hetero` (8 источников),
  `selection-preview-atlas-conflict` (1) и `selection-preview-nova-foreign`
  (1) объявлены в самом fixture; существующие элементы очереди не мутированы.
- **Predictions.** Гетерогенный preview покрывает все четыре:
  `WILL_MOVE` (README и `invoice.TXT` с приоритетом 10 против 100),
  `WILL_MANUAL_REVIEW` (`NO_SCENARIO`), `REQUIRES_DECISION` (occupied/duplicate/
  manual-name) и `NOT_READY` (источник больше не готов, target=null).
- **Collisions.** `EXISTING_TARGET` несёт метаданные занятой цели,
  `DUPLICATE_PLAN_TARGET` перечисляет обоих участников и не имеет
  existing-метаданных, `MANUAL_REVIEW_NAME` не имеет target и ссылается на
  занятый файл плоского ручного разбора `_manual_review/atlas`.
- **RULE_CONFLICT.** Изолированный preview использует объявленный scenario
  RuleSet `rule-set-atlas-eq-diff` (general+invoices, приоритет 100, разные
  цели): два matched, `selected_rule=null`, target=null. Primary previews
  используют полный published `rule-set-atlas-published`; ни одна ссылка
  `matched_rules`/`selected_rule` не имеет `version_id=null`.
- **Preflight.** Принятые DIRECT/PREVIEWED и same-user-new-session ожидают 202,
  `batch_created=true`, отсутствие файловых операций и будущий batch ID/RuleSet
  (payload результата — LT-03.4a). Отказы до принятия: 409 `SELECTION_CHANGED`
  (DIRECT источник изменился/исчез), 409 `STALE_PREVIEW` (PREVIEWED источник,
  правила, цель, TTL), 409 `SELECTION_EXPIRED`, 409 `INVALID_STATE`
  (pairing/company), 404 `NOT_FOUND`, 403 `FORBIDDEN`; каждый с реальным
  запросом, предусловием и `batch_created=false`/`file_operations=false`.
- **Post-acceptance.** `SOURCE_CHANGED` и `ALREADY_PROCESSING` описаны как
  пофайловые исходы уже принятой партии (HTTP 200, `global_refusal=false`), а
  не как общий preflight-отказ.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\preview_preflight.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (39 checks, 0 failures)`, `Fixtures: 110`,
  `Preview/preflight expectations: 6 preview(s), 134 row(s), 18 preflight
  scenario(s), 15 rejection(s), 4 post-acceptance outcome(s)`; FIX-PREVIEW-001/
  002/003 — PASS.
- `unittest discover` → `Ran 342 tests ... OK` (было 287; добавлено 55).
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами. `--update-checksums` не меняет пересчитанный manifest.
- `git diff --check` → только предупреждения LF/CRLF, пробельных ошибок нет.
- Негативные self-тесты: неверный total/TTL/revision, дрейф selected_count,
  выбранное правило не минимального приоритета, `NO_SCENARIO` с совпадением,
  пропавшие existing-метаданные, неполный список участников duplicate,
  код у принятого сценария, DIRECT как `STALE_PREVIEW` и неверная
  schema-классификация — отклоняются валидаторами.

## ID-модель для следующего leaf (LT-03.4a)

- Снимки: `selection-atlas-allmatching-120`, `selection-atlas-explicit-one`,
  `selection-atlas-explicit-multiple`, `selection-preview-atlas-hetero`,
  `selection-preview-atlas-conflict`, `selection-preview-nova-foreign`.
- Preview: `preview-atlas-allmatching-120` (page1/page2), `preview-atlas-explicit-one`,
  `preview-atlas-explicit-multiple`, `preview-atlas-hetero`,
  `preview-atlas-conflict`, `preview-nova-foreign`.
- Принятые preflight: `PF-DIRECT-FRESH` (`batch-atlas-direct-fresh`),
  `PF-PREVIEWED-FRESH` (`batch-atlas-previewed-fresh`),
  `PF-SAME-USER-NEW-SESSION` (`batch-atlas-same-user-session`).
- RuleSet: published `rule-set-atlas-published` (general v1 + invoices v1);
  scenario `rule-set-atlas-eq-diff` только для изолированного конфликта.
- Batch payload/outcomes/attempts — предмет LT-03.4a; здесь объявлены только
  ожидаемые future batch ID и RuleSet.

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** TTL-часы,
  занятость целей, гонки и физическая готовность не проверялись.
- Matcher/priority resolver/target derivation/preflight не реализуются:
  значения объявлены литерально и сверяются между собой; `NOT_READY`,
  `MANUAL_REVIEW_NAME` и `DUPLICATE_PLAN_TARGET` — изолированные конечные
  сценарии, а не доказательство поведения backend.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.3b (независимая сверка prediction/
  collision kinds, привязки к снимкам и RuleSet, preflight-пар и негативных
  мутаций), затем LT-03.4a (фактические партии и файловые исходы).
- **Блокирующая зависимость:** нет.

# LT-03.4a — эталон фактических партий и файловых исходов

Дополнение фиксирует результат leaf LT-03.4a (parent LT-03.4, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечный независимый эталон принятых партий и пофайловых исходов
  поверх неизменяемых снимков LT-03.3a, принятых preflight LT-03.3b и полных
  определений LT-03.2a/2b; matcher, priority resolver, target-name derivation,
  executor и файловые операции не реализуются.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.4/LT-03.4a; D-03/D-06; API §8;
  TZ QUEUE-07…10, FILE-01…06/08/09; QA §4/8; MATRIX Q-031…037/039; OAS
  `Batch`/`BatchSummary`/`BatchPage`/`Outcome`/`OutcomeCounts`/`BatchState`/
  `OutcomeState`/`OutcomeReasonCode`; `contracts/semantics.md`.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/batch_outcomes.json` | новый эталон: 7 партий (ACCEPTED/RUNNING/COMPLETED/COMPLETED_WITH_ISSUES/RECOVERY_REQUIRED), 9 страниц, 260 outcomes, 7 summary, 23 mutations, 21 link, inventory-контракт, coverage Q-031…037/039 |
| `contracts/examples/sorting/batch-*.json` | 9 публичных `Batch` + 1 `BatchPage` истории |
| `tests/contract/contractlib/batch_outcomes.py` | declarative loader/materializer/checker + `--write-examples`; переиспользует `queue_selections`/`preview_preflight`/`rule_expectations`, не дублирует matcher |
| `tests/contract/contractlib/fixture_checks.py` | FIX-BATCH-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/contractlib/verify.py` | `run_checks(..., include_fixtures=True)`; default сохраняет полный набор |
| `tests/contract/test_batch_outcomes.py` | 50 тестов: структура/схемы/state/reason/counts/pagination/placements/preflight links/history/inventory/негативные мутации |
| `tests/contract/test_verify_contract.py` | `include_fixtures=False` **только** в OAS-corruption unit-тестах |
| `tests/contract/test_synthetic_corpus.py` | 120 публичных примеров, FIX-BATCH-счётчики |
| `fixtures/synthetic/manifest.json` | fixture `batch-outcomes`, 10 привязанных examples, пересчитанные канонические checksums; версия корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.4a и команда генерации |
| `docs/team/WP-03_SYNTHETIC_HANDOFF.md` | этот раздел; исправлены исторические счётчики LT-03.3b (15 mutations/49 tests → 17/55) |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI и
`corpus.json`/`rule_expectations.json`/`dictionary_lifecycle.json`/
`queue_selections.json`/`preview_preflight.json` **не изменялись**. Корпус
`1.2.0`.

## Что именно зафиксировано

- **Три принятых preflight получают реальные Batch payloads.**
  `PF-DIRECT-FRESH` → `batch-atlas-direct-fresh` (ACCEPTED, 120),
  `PF-PREVIEWED-FRESH` → `batch-atlas-previewed-fresh` (RUNNING, 120, preview
  `preview-atlas-allmatching-120`), `PF-SAME-USER-NEW-SESSION` →
  `batch-atlas-same-user-session` (COMPLETED_WITH_ISSUES, 3). `future_batch_id`,
  selection, RuleSet, execution_mode и preview_id сверены со ссылками LT-03.3b.
- **Полный 120-элементный план и пагинация.** Обе 120-партии дают страницу
  100 + 20; membership точно равен `selection-atlas-allmatching-120`; страница
  не подменяется текущей выдачей.
- **Все 5 BatchState:** ACCEPTED (только PENDING), RUNNING (есть PENDING/
  PROCESSING, completed < selected), COMPLETED (все SORTED), COMPLETED_WITH_ISSUES
  (нет незавершённых, есть хотя бы один несортированный терминальный исход),
  RECOVERY_REQUIRED (`finished_at=null`, `recovery_required ≥ 1`).
- **Все 8 OutcomeState и 9 reason_code** встречаются в конечных сценариях;
  точное соответствие state→reason проверено.
- **Counts.** Первые пять счётчиков суммируются в `completed_count`;
  `recovery_required` — незавершённые; `completed + recovery ≤ selected`.
- **Размещения.** SORTED: `actual_location == planned_target` и равен
  литеральному `target.relative_directory + target_stem + последний суффикс`
  выбранного опубликованного правила. Занятая цель: существующий объект
  неизменён, источник остаётся (`actual_location == source`). Дубликат плановой
  цели: оба участника REQUIRES_DECISION/TARGET_OCCUPIED, победителя нет.
  NO_SCENARIO/RULE_CONFLICT: плоская папка ручного разбора с неизменённым
  basename, `planned_target=null`. Занятое имя ручного разбора: источник
  остаётся. QUARANTINED/TECHNICAL_ERROR: только подтверждённый перенос, у
  `actual_location` есть путь карантина. RECOVERY_REQUIRED: `finished_at=null`,
  неизвестное размещение → `actual_location=null`, известный источник →
  `actual_location=source`. SKIPPED: ALREADY_PROCESSING/SOURCE_CHANGED/
  SOURCE_MISSING не выполняют собственной мутации, `actual_location=null`
  (для SOURCE_MISSING это требует схема).
- **Изолированный гетерогенный принятый выбор** `selection-batch-atlas-hetero`
  (7) = preview hetero без `NOT_READY`; post-acceptance source-change вынесен
  в отдельный SKIPPED-сценарий `batch-atlas-technical`. Исходные snapshot/
  revision/rules не мутированы.
- **История.** `BatchPage` из `BatchSummary` сортирована `created_at DESC,
  batch_id DESC`; summary повторяет actor/counts/batch_id соответствующей
  партии; все партии присутствуют.
- **Inventory/hash contract.** Раздел `inventory` — логическое ожидание
  (`kind=logical-inventory-expectation`), не измеренная ФС. Для подтверждённых
  переносов источник отсутствует, назначение присутствует, содержимое
  сохранено; для решений/пропусков назначение не заявлено. Content tag —
  детерминированная логическая метка (`lt034a-content-*`) по seed, не реальный
  sha256. Файлы не создаются и не читаются.
- **Негативные мутации.** 23 конечные мутации отклоняются валидаторами
  (state/reason, counts, terminal/unfinished, page fullness, membership/
  revision, duplicate winner, manual review target/basename, occupied source,
  quarantine/recovery/skip placement, history order, inventory source leftover,
  attempt uniqueness).

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\batch_outcomes.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (42 checks, 0 failures)`, `Examples: 127`,
  `Fixtures: 120 public example(s)`, `Batch/outcome expectations: 7 batch(es),
  9 page(s), 260 outcome(s), 7 summary(ies), 23 mutation(s)`; FIX-BATCH-001/002/
  003 — PASS.
- `unittest discover` → `Ran 392 tests ... OK` (было 342; добавлено 50).
- `test_batch_outcomes.py` → 50 OK; `test_preview_preflight.py` → 55 OK
  (исторические 49 исправлены).
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-BATCH-003). `--update-checksums` не меняет
  пересчитанный manifest.
- Производительность: полная suite сокращена с ~670 с до ~343 с за счёт
  `run_checks(include_fixtures=False)` **только** в OAS-corruption unit-тестах;
  CLI и полный positive suite по-прежнему выполняют все fixtures.

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Физические
  перемещения, карантин, checksums, TTL-часы, гонки и восстановление не
  выполнялись и не заявляются; inventory — логический контракт.
- Matcher/priority resolver/target derivation/executor/recovery не реализуются:
  значения объявлены литерально и сверяются между собой. Изолированные
  сценарии не доказывают поведение backend.
- Сценарии `lost response`/идемпотентность/claim overlap двух акторов/
  logout-reload/restart — LT-03.4b; здесь только конечные пофайловые исходы.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## ID-модель для следующего leaf (LT-03.4b)

- Партии: `batch-atlas-direct-fresh`, `batch-atlas-previewed-fresh`,
  `batch-atlas-same-user-session`, `batch-atlas-hetero`, `batch-atlas-conflict`,
  `batch-atlas-sorted`, `batch-atlas-technical`.
- Изолированные выборы: `selection-batch-atlas-hetero`,
  `selection-batch-atlas-conflict`, `selection-batch-atlas-sorted`,
  `selection-batch-atlas-technical`.
- Attempt IDs: `attempt-<batch_id>-<item_id>`; quarantine-каталог
  `_quarantine/atlas/<attempt_id>/`, manual review `_manual_review/atlas/`.
- RuleSet: published `rule-set-atlas-published`; scenario `rule-set-atlas-eq-diff`.

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.4a (независимая сверка state/reason,
  counts/attempts/placements, pagination, inventory-контракта, preflight/history
  links и негативных мутаций), затем LT-03.4b (lost response/идемпотентность/
  claim overlap/restart).
- **Блокирующая зависимость:** нет.

# LT-03.4b — эталон операционных повторов, пересечений и перезапусков

Дополнение фиксирует результат leaf LT-03.4b (parent LT-03.4, WP-03, Epic
E-01). **Status:** IN_PROGRESS (публикация отложена D-06).

## Задача и основание

- **Цель:** конечные операционные сценарии поверх принятых партий/размещений
  LT-03.4a и preflight/ошибок LT-03.3b: идемпотентный повтор после потерянного
  ответа и истечения зависимости, изменённое тело, scope пользователя, новый
  ручной повтор, claim overlap двух акторов, source change до/после принятия,
  logout/reload continuation, поздняя цель, обратный порядок дубликата цели, три
  точки перезапуска и containment Q-044. Реальный concurrency/FS/recovery не
  реализуется; fault-точки, барьеры и durable intent — логические метки.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.4/LT-03.4b; D-03/D-06; API
  §2 (идемпотентность) и §8 (pre/post-acceptance); TZ QUEUE-07…10, AUTH-03,
  FILE-08/09; QA §4/8; MATRIX Q-028…030/031/032/040/044; OAS
  `BatchCreateRequest`/`Batch`/`Outcome`/`ErrorResponse`/`AuditEvent`/
  `AuditAction`/`ErrorCode`; `contracts/semantics.md`.

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/batch_scenarios.json` | новый эталон: 12 сценариев (IDEMPOTENCY/OVERLAP/SOURCE_CHANGE/CONTINUATION/LATE_TARGET/DUPLICATE_TARGET/RESTART/CONTAINMENT), 3 изолированных выбора, 3 изолированные партии, 4 replay, 9 containment cases, 18 audit events, 41 link, 23 mutation, coverage Q-028…030/031/032/040/044 |
| `contracts/examples/sorting/batch-overlap-winner.json`, `batch-overlap-loser.json` | 2 публичных `Batch` изолированных overlap-партий |
| `tests/contract/contractlib/batch_scenarios.py` | declarative loader/materializer/checker + `--write-examples`; переиспользует `batch_outcomes`/`preview_preflight`, не дублирует executor |
| `tests/contract/contractlib/fixture_checks.py` | FIX-SCN-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_batch_scenarios.py` | 56 тестов: структура/схемы/links/coverage/identity/inventory, идемпотентность, overlap, source change, continuation, late target, duplicate reversed, restart, containment, audit, негативные мутации |
| `tests/contract/test_synthetic_corpus.py` | 122 публичных примера, FIX-SCN-счётчики |
| `fixtures/synthetic/batch_outcomes.json` | точечно исправлен `inventory.content_recipe`: логическая метка `tag_prefix + item_id` вместо мнимого `deterministic-synthetic-bytes` по company/size (ранее расходилось с фактическим `content_tag`); checksums пересчитаны |
| `fixtures/synthetic/manifest.json` | fixture `batch-scenarios`, 2 привязанных examples, пересчитанные канонические checksums; версия корпуса **1.2.0 без изменения** |
| `README.md` | раздел LT-03.4b и команда генерации |
| `docs/team/WP-03_SYNTHETIC_HANDOFF.md` | этот раздел |

OAS, `contracts/semantics.md`, control plane, backlog, backend/UI и
`corpus.json`/`rule_expectations.json`/`dictionary_lifecycle.json`/
`queue_selections.json`/`preview_preflight.json` **не изменялись**.

## Что именно зафиксировано

- **Идемпотентность (Q-029/030).** `SCN-IDEM-REPLAY-DIRECT`/`-PREVIEWED`:
  ключ/пользователь/тело повторяются после потерянного ответа (before expiry) и
  после истечения snapshot/preview (after expiry) и возвращают ту же партию с
  `new_attempts=0`. `SCN-IDEM-MODIFIED-BODY`: другое тело с тем же ключом —
  409 `IDEMPOTENCY_KEY_REUSED` через `ErrorResponse`. `SCN-IDEM-DIFFERENT-USER-SCOPE`:
  та же строка ключа у другого пользователя — отдельный scope, своя партия, не
  конфликт. `SCN-MANUAL-RETRY-NEW-KEY`: отказ `SELECTION_CHANGED` без партии и
  попыток, затем новый ключ + новый выбор → новая партия и новая попытка;
  attempt IDs глобально уникальны.
- **Claim overlap (Q-028/030).** `SCN-OVERLAP-TWO-ACTORS`: `overlap-shared-pdf`
  входит в оба выбора с одинаковыми location/revision; победитель `SORTED`,
  проигравший `SKIPPED`/`ALREADY_PROCESSING`, `actual_location=null`, без второго
  перемещения; содержательная ревизия не меняется claim-ом; независимые
  безопасные элементы обоих акторов `SORTED`; барьер фиксирует claim победителя
  раньше попытки проигравшего.
- **Source change (Q-028/029).** До принятия — отказ `SELECTION_CHANGED`
  (DIRECT) и `STALE_PREVIEW` (PREVIEWED) без партии/ФС; после принятия —
  `SKIPPED`/`SOURCE_CHANGED`, `actual_location=null`, возврат к `WAITING_READY`,
  мутации нет.
- **Continuation (Q-030, AUTH-03).** После logout/reload другой пользователь
  читает ту же партию с исходным автором; операции отмены партии нет, новый
  зритель не становится автором, партия не создаётся повторно.
- **Поздняя цель (Q-032).** Цель, появившаяся после фиксации плана, даёт
  `REQUIRES_DECISION`/`TARGET_OCCUPIED`, источник остаётся, существующий объект
  неизменён, замены нет.
- **Дубликат цели (Q-031).** Обратный порядок входных ID даёт тот же результат
  всем участникам (`REQUIRES_DECISION`/`TARGET_OCCUPIED`), победителя нет,
  независимый безопасный файл проходит.
- **Перезапуск (Q-040, FILE-09).** Три точки: до мутации (intent сохранён,
  повтор ключа возвращает ту же партию), после доказанной фиксации (один
  результат без второго перемещения), неоднозначная (`RECOVERY_REQUIRED`, без
  слепого повтора, зарегистрированный `operation_id`). `live_evidence=false`.
- **Containment (Q-044, FILE-08).** До партии: 404 `NOT_FOUND`, 403 `FORBIDDEN`,
  409 `INVALID_STATE` (чужая компания), 422
  `INVALID_TARGET`/`PATH_OUTSIDE_ROOT`/`VALIDATION_ERROR` — только коды,
  объявленные соответствующей операцией OAS; после принятия: подтверждённый
  `QUARANTINED`/`TECHNICAL_ERROR` или безопасный `RECOVERY_REQUIRED` без
  выдуманного исхода; вне песочницы доступа нет.
- **Audit для LT-03.5b.** 18 ожидаемых событий с phase (`ACCEPT`/
  `ATTEMPT_START`/`ATTEMPT_FINISH`/`RECOVERY`/`SESSION`), `AuditAction`,
  категорией/результатом, автором и связями `batch_id`/`attempt_id`/`item_id`/
  `request_id`/`operation_id`/`source_attempt_id`; уникальный
  attempt/phase-ключ исключает дубли; `RECOVERY_REQUIRED` связывает
  `source_attempt_id` с попыткой.
- **Негативные мутации.** 23 конечные мутации отклоняются валидаторами
  (replay/attempt, modified body, scope, retry key, claim winner/double claim,
  revision drift, source change location/queue, continuation author/cancel,
  duplicate winner, restart blind retry/ambiguous final, containment outside
  access/wrong code, audit action/duplicate key/system actor, coverage, UUID).
- **Изолированные данные.** Три выбора (`selection-overlap-worker1`,
  `selection-overlap-worker2`, `selection-batch-atlas-retry`) и три партии
  (`batch-overlap-winner`, `batch-overlap-loser`, `batch-atlas-retry`) используют
  immutable `rule-set-atlas-published`; существующие batch IDs не
  переиспользуются с другим actor/snapshot/RuleSet.

## V-S: точные команды и фактические результаты

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest tests.contract.test_batch_scenarios
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\batch_scenarios.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (45 checks, 0 failures)`, `Examples: 127`,
  `Fixtures: 122 public example(s)`, `Batch scenario expectations: 12 scenario(s),
  4 replay(s), 9 containment case(s), 18 audit event(s), 23 mutation(s)`;
  FIX-SCN-001/002/003 — PASS.
- `test_batch_scenarios.py` → 56 OK.
- `unittest discover` → `Ran 448 tests ... OK` (было 392; добавлено 56).
- `pip check` → `No broken requirements found.`
- `--write-examples` идемпотентно; повторная генерация совпадает с
  закоммиченными файлами (FIX-SCN-003). `--update-checksums` не меняет
  пересчитанный manifest.
- `git diff --check` → PASS (только предупреждения CRLF).

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.** Реальные гонки,
  потеря ответа, перезапуск, claim, файловые операции, TTL-часы и восстановление
  не выполнялись; fault-точки/барьеры/durable intent — логические требования.
- Matcher/priority resolver/target derivation/executor/recovery/concurrency не
  реализуются: значения объявлены и сверяются между собой. Сценарии не
  доказывают поведение backend.
- `WAITING_READY` для изменившегося источника — объявленное ожидаемое состояние
  очереди, не materialized QueueResponse.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker
  не выполняет (D-06).

## ID-модель для следующего leaf (LT-03.5a/5b)

- Изолированные партии LT-03.4b: `batch-overlap-winner`, `batch-overlap-loser`,
  `batch-atlas-retry`.
- Изолированные выборы: `selection-overlap-worker1`, `selection-overlap-worker2`,
  `selection-batch-atlas-retry`.
- Audit events: `AUD-BATCH-ACCEPT-*`, `AUD-ATTEMPT-*`, `AUD-RECOVERY-REQUIRED`,
  `AUD-LOGOUT-SYSTEM`; `source_attempt_id` у recovery указывает на attempt
  `attempt-batch-atlas-technical-batch-tech-recovery-unknown`.
- RuleSet: published `rule-set-atlas-published`.

## Статус и следующий владелец

- **Следующий владелец:** reviewer LT-03.4b (независимая сверка replay/attempt,
  overlap/no-second-move, source change, continuation, late/duplicate target,
  restart intent, containment-кодов и audit-связей), затем LT-03.5a (quarantine/
  return) и LT-03.5b (audit) на основе audit-ожиданий этого leaf.
- **Блокирующая зависимость:** нет.

# LT-03.5a — эталон карантина и возврата

Дополнение фиксирует результат leaf LT-03.5a (parent LT-03.5, WP-03, Epic E-01).
**Status:** IN_PROGRESS (публикация отложена D-06). Это документарное дополнение
закрывает единственное BLOCKING-замечание FE §7 handoff; код/данные не менялись,
полный прогон не повторялся.

## Задача и основание

- **Цель:** конечный, внутренне связанный эталон подтверждённого карантина и
  ручного возврата поверх фактического исхода LT-03.4a, пригодный для LT-03.5b
  (audit) и финального аудита.
- **Основание:** AGENTS; FRONTEND_BACKLOG LT-03.5/LT-03.5a; D-03/D-06; API
  §2/9/10/11; TZ FILE-07/QUEUE-01/AUD-01/02; QA §4/8; MATRIX Q-029 (return)/Q-038/
  Q-043; OAS `QuarantineItem`/`QuarantinePage`/`QuarantineReturnRequest`/
  `QuarantineReturnResponse`/`QueueItem`/`ErrorResponse`/`AuditEvent`;
  `fixtures/synthetic/batch_outcomes.json`.

## Версия, seed и контрольная сумма

- OAS `info.version = 1.0.0`; `contract_version = 1.0.0`.
- `fixture_set = wiseway-quarantine-returns`, `version = 1.0.0`,
  `seed = wiseway-demo-seed-2031`, `corpus_version = 1.2.0` (корпус не менялся).
- `content_hash(quarantine_returns.json) = 301486835a04079e33520a182087092a61c6f358beea5b47093652d9ec5dbccf`
  (совпадает с `manifest.checksum.fixtures["quarantine-returns"]`).

## Изменённые/добавленные файлы

| Файл | Характер |
|---|---|
| `fixtures/synthetic/quarantine_returns.json` | новый эталон: 2 записи карантина, 11 сценариев, 2 replay, 7 error, 2 audit-дескриптора, 21 link, 22 мутации, логический `return_inventory`, coverage Q-029/038/043 |
| `contracts/examples/quarantine/*.json` | 5 публичных `QuarantineItem`/`QuarantinePage`/`QuarantineReturnRequest`/`QuarantineReturnResponse` |
| `contracts/examples/errors/error-quarantine-*.json`, `error-original-path-occupied.json` | 7 публичных `ErrorResponse` |
| `tests/contract/contractlib/quarantine_returns.py` | загрузчик/материализатор/валидатор + `--write-examples` |
| `tests/contract/test_quarantine_returns.py` | 52 теста |
| `fixtures/synthetic/batch_outcomes.json` | одобренная точечная правка `inventory.note` |
| `fixtures/synthetic/manifest.json` | fixture `quarantine-returns`, 12 examples, checksums |
| `tests/contract/contractlib/fixture_checks.py` | FIX-QR-001/002/003 |
| `tests/contract/contractlib/report.py`, `__init__.py`, `verify_contract.py` | счётчики/экспорт/строка отчёта |
| `tests/contract/test_synthetic_corpus.py` | 122→134 examples, FIX-QR и счётчики |
| `README.md` | раздел LT-03.5a и команда подготовки |

OAS, `contracts/semantics.md`, control plane, backlog и backend/UI **не
изменялись**.

## Что именно зафиксировано

- **Подтверждённая запись** `quarantine-atlas-batch-tech-quarantine` выводится из
  фактического LT-03.4a `batch-atlas-technical`/`batch-tech-quarantine`
  `QUARANTINED`/`TECHNICAL_ERROR`: item, `source_attempt_id`
  `attempt-batch-atlas-technical-batch-tech-quarantine`, подтверждённый
  `location` (`_quarantine/atlas/<attempt_id>/…`), `original_location` и
  `filename`. `RECOVERY_REQUIRED`-исходы той же партии
  (`batch-tech-recovery-unknown/known`) в подтверждённый список не входят.
- **Две записи с одним `quarantine_id` — альтернативные наблюдения** одного
  предмета: revision 1 (`can_return=true`, `recovery_operation_id=null`) и
  revision 3 (`can_return=false`, зарегистрированный
  `recovery_operation_id=return-atlas-batch-tech-quarantine-recovery`). Это
  разные состояния/сценарии, а не две одновременные записи в одном списке.
- **Успех** `QR-RETURN-SUCCESS`: 200, `return_operation_id`
  `return-atlas-batch-tech-quarantine`, `QueueItem` `WAITING_READY`,
  `selectable=false`, `active_attempt_id=null`, `reason_code=null`, без
  автосортировки/нового batch/attempt, `source` — исходный путь, `filename` —
  basename. `source_attempt_id` и `operation_id` согласованы для audit.
- **Конфликты:** comment 0/501 → 422 `VALIDATION_ERROR` (схемно невалидно);
  устаревшая revision → 409 `QUARANTINE_VERSION_CONFLICT`; занятый исходный путь
  → 409 `ORIGINAL_PATH_OCCUPIED` (объекты сохранны, переноса нет); неизвестный ID
  → 404 `NOT_FOUND`; уже возвращённая запись с новым ключом → 409 `INVALID_STATE`;
  неоднозначный возврат → 409 `RECOVERY_REQUIRED` с непустым
  `error.operation_id`, `can_return=false` с тем же `recovery_operation_id`, без
  выдуманного успешного размещения (`actual_placement=null`).
- **Идемпотентность:** повтор того же ключа/пользователя/тела возвращает прежний
  успех или зарегистрированный recovery без второго перемещения, несмотря на
  изменившуюся revision; другое тело → 409 `IDEMPOTENCY_KEY_REUSED`; та же строка
  ключа у другого пользователя — отдельный scope (409 `INVALID_STATE` по текущему
  состоянию, не глобальный конфликт ключа).
- **`can_return`** — серверный флаг стабильности OAS, не изобретённое право/роль;
  `false` только вместе с зарегистрированной recovery-операцией.
- **Audit-дескрипторы** `AUD-QR-RETURNED-SUCCESS`/`AUD-QR-RETURN-RECOVERY` с
  `evidence=false`: ожидаемые ID для LT-03.5b, не записанное audit evidence.
- **`return_inventory`** — логическое ожидание (без записи/чтения файлов):
  успешный возврат убирает файл из карантина и восстанавливает исходный путь с
  сохранением содержимого; неоднозначный возврат не заявляет ни одну сторону;
  prior batch неизменён.
- **Возврат в исходный `Archive/...` путь** — только изолированная синтетическая
  логическая конфигурация этого эталона, а не описание продуктовых настроек или
  реального sandbox.

## V-S: ранее выполненные команды и фактические результаты

Приведённые ниже прогоны были выполнены при реализации leaf **до** данного
документарного дополнения; для правки только документации они **не
повторялись**. Windows, Python 3.14.7, `.venv-contract`:

```powershell
.\.venv-contract\Scripts\python.exe tests\contract\verify_contract.py
.\.venv-contract\Scripts\python.exe -m unittest tests.contract.test_quarantine_returns
.\.venv-contract\Scripts\python.exe -m unittest discover -s tests\contract -p "test_*.py"
.\.venv-contract\Scripts\python.exe -m pip check
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\quarantine_returns.py --write-examples
.\.venv-contract\Scripts\python.exe tests\contract\contractlib\synthetic.py --update-checksums
git diff --check
```

- `verify_contract.py` → `RESULT: PASS (48 checks, 0 failures)`, `Examples: 127`,
  `Fixtures: 134 public example(s), 164 corpus file(s) and 8 lifecycle payload(s)`,
  `Quarantine/return expectations: 2 record(s), 11 scenario(s), 2 replay(s),
  2 audit descriptor(s), 22 mutation(s)`; FIX-QR-001/002/003 — PASS.
- `-m unittest tests.contract.test_quarantine_returns` → `Ran 52 tests ... OK`.
- `-m unittest discover -s tests\contract` → `Ran 500 tests ... OK` (636.156 s).
- `-m pip check` → `No broken requirements found.`
- `--write-examples` и `--update-checksums` идемпотентны; повторный запуск не
  меняет рабочее дерево.
- `git diff --check` → только предупреждения LF/CRLF, пробельных ошибок нет.

## Repair: документарное закрытие FE §7

Reviewer подтвердил все code/data AC и прогоны (runner 48 / full 500 / targeted
52) и оставил единственное BLOCKING-замечание — отсутствие этого раздела
handoff. Repair **docs-only**: код, fixture, examples, manifest/checksums и тесты
не менялись; полный прогон для правки только документации не повторялся, что
соответствует V-H (проверка полноты/ссылок/границ handoff). `git diff --check`
для документарной правки достаточно.

## Ограничения и явно не выполненное

- Это **S**-уровень: схемы/статические проверки и литеральный эталон.
  **M (mock/UI), A (реальный API/ФС), E (E2E) — NOT_RUN.**
- Реальный возврат, файловая безопасность, карантин, checksums, TTL-часы, гонки,
  idempotency-store и recovery не выполнялись и не заявляются; `return_inventory`
  — логический контракт, физическая ФС не создавалась и не читалась.
- Audit-дескрипторы — ожидания, а не записанные события; `evidence=false`.
- Backend/UI/control plane/backlog не затрагивались. Staging/commit/push worker не
  выполняет (D-06).

## Статус и следующий владелец

- **Следующий владелец:** LT-03.5b — связанный audit по dictionary/batch/attempt/
  return событиям, BUSINESS/SYSTEM/nullable actor/заблокированные авторы,
  фильтры/UTC день/cursor/new events, безопасные request/operation/
  source_attempt IDs; использует audit-ожидания LT-03.4b и LT-03.5a.
- **Блокирующая зависимость:** нет.
