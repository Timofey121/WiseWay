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
