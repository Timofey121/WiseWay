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
а также валидирует все встроенные examples против канонических схем. Негативные
self-тесты подтверждают, что runner обнаруживает испорченный контракт/payload.
Исполнение поиска, файловые гарантии и E2E требуют будущего приложения.
