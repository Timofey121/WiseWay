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

Ожидания точных поисковых запросов, порядка и фасетов формируются в следующем
leaf LT-03.1b; здесь публикуется только конечный корпус и его инвентарь.
Списки natural/русской сортировки в `search_inputs` — неупорядоченные
кандидатные входы; точный порядок определяет LT-03.1b.
