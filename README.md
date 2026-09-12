# Wise Way

Wise Way — сервис иерархического поиска по метаданным и ручной сортировки входящих файлов.

В репозитории находятся frontend, backend и общий OpenAPI-контракт. Backend написан на Python 3.11+ и FastAPI, хранит операционное состояние в SQLite, выполняет файловые операции отдельным worker и поддерживает OpenSearch для большого поискового индекса.

- [OpenAPI 3.1.1](contracts/openapi/wiseway-v1.yaml) — единый контракт frontend и backend.
- [Семантика API](contracts/semantics.md) — правила, которые не выражаются схемами.
- [Развёртывание](docs/deployment.md) и [эксплуатация](docs/operations.md).
- [Производительность](docs/performance.md) и [архивный поиск](docs/archive-search.md).

## Backend

Нужны Python 3.11+ и `uv`.

```sh
uv sync --frozen
uv run wiseway init-demo
uv run wiseway serve
```

Worker запускается отдельно:

```sh
uv run wiseway worker
```

API доступен по адресу `http://127.0.0.1:8000/api/v1`, health check — `GET /api/v1/health`. Данные локальной среды находятся в `.wiseway/` и не попадают в Git.

## Frontend

```sh
cd frontend
npm ci
npm run dev
```

Сгенерированный API-клиент строится из `contracts/openapi/wiseway-v1.yaml`. После изменения контракта выполните команды генерации и проверки из `frontend/package.json`.

## Проверка

```sh
uv run pytest -q
uv run ruff check backend infra/scripts
uv run ruff format --check backend infra/scripts
cd frontend && npm test && npm run build
```

Для production подготовлены Docker Compose, TLS gateway, CI, release workflow, backup/restore и systemd-конфигурация. Текущие ограничения масштабирования и результаты нагрузочных прогонов описаны в `docs/performance.md`.
