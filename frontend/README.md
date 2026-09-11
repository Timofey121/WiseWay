# WiseWay — frontend

Минимальная рабочая основа (scaffold) frontend-приложения WiseWay. Сейчас в
каталоге находятся конфигурация инструментов, точка входа, smoke-тесты и
generated API-артефакты из единственного публичного OAS. Продуктовые экраны,
навигация, дизайн-система и mock-сценарии появятся в следующих leaf-задачах
(EPIC E-02, WP-05/WP-06/WP-07).

Выбранный toolchain, точные версии и политика lock-файла закреплены в
[ADR-0001. Frontend toolchain WiseWay](docs/ADR-0001-frontend-toolchain.md).

## Требования

- Node.js `>=22 <25` (проверено на `v24.20.0`).
- npm `>=11 <12` (проверено на `11.19.0`).

## Установка

Из каталога `frontend/`:

```powershell
npm ci
```

`npm ci` устанавливает ровно дерево зависимостей из `package-lock.json`.
Lock-файл коммитится; повторная установка не должна изменять его.

## Команды

| Команда | Назначение |
|---|---|
| `npm run dev` | Запускает dev-сервер Vite (по умолчанию `http://localhost:5173`). |
| `npm run build` | Production-сборка Vite в `frontend/dist`. |
| `npm run preview` | Локальный просмотр собранного `frontend/dist` (по умолчанию `http://localhost:4173`). |
| `npm run typecheck` | Проверка типов `tsc --noEmit` без эмита. |
| `npm run lint` | ESLint 9 (flat config) по проекту. |
| `npm run test` | Unit/component smoke-тесты: Vitest + Testing Library в jsdom. |
| `npm run test:browser` | Browser smoke-тест Playwright; сначала выполняет `npm run build`. |
| `npm run generate:api` | Генерация `src/api/generated/schema.ts` и `openapi.json` из `contracts/openapi/wiseway-v1.yaml`. |
| `npm run generate:api:check` | Перегенерация во временный каталог и сравнение с закоммиченными артефактами (проверка «без diff»). |

## Генерация API-типов и клиента из OpenAPI

Единственный источник структуры API — `contracts/openapi/wiseway-v1.yaml`
(OpenAPI 3.1.1, `info.version: 1.0.0`, 33 `operationId`). Второй контракт не
создаётся, ручные DTO на клиенте запрещены.

Из OAS воспроизводимо генерируются два артефакта (оба коммитятся):

| Артефакт | Назначение |
|---|---|
| `src/api/generated/schema.ts` | TypeScript-типы всех операций и схем (`openapi-typescript` 7). Импорт: `import type { paths, components, operations } from '@/api/generated/schema'`. |
| `src/api/generated/openapi.json` | Тот же OAS, сконвертированный YAML → JSON; используется runtime-mocks (WP-06/WP-07), которым не нужен YAML-парсер в браузере. |

Типизированный runtime-клиент `src/api/generated/client.ts` строится поверх
`schema.ts` через `openapi-fetch` и не дублирует схемы. Фабрика:

```ts
import { createWiseWayClient } from '@/api/generated/client'

const api = createWiseWayClient() // baseUrl по умолчанию — '/api/v1'
const { data } = await api.GET('/health')
```

`baseUrl` и `fetch` настраиваются: mock-режим подменяет их, не меняя типы
запросов/ответов.

Генерация и проверка воспроизводимости:

```powershell
npm run generate:api
git diff --exit-code -- src/api/generated   # пусто при неизменном OAS
npm run generate:api:check                  # без Git: сравнение с временным каталогом
```

`schema.ts` и `openapi.json` генерируются целиком и не редактируются вручную:
изменения будут перезаписаны следующей генерацией. Обоснование выбора
генератора и клиента — в [ADR-0001](docs/ADR-0001-frontend-toolchain.md) §5.

## Структура

```text
frontend/
  index.html
  scripts/
    generate-api.mjs          генерация schema.ts + openapi.json из OAS
    check-generated.mjs       проверка повторной генерации без diff
  src/
    main.tsx            точка входа React
    App.tsx             минимальный placeholder (без экранов продукта)
    features/{auth,search,dictionaries,sorting,quarantine,audit}/
    api/
      generated/        generated-артефакты (schema.ts, openapi.json) и client.ts
    mocks/              placeholder для schema-valid mocks (WP-06/WP-07)
  tests/
    App.test.tsx        component smoke-тест
    api/client.test.ts  runtime-проверки запросов клиента A/B/C
    api/generated-types.test.ts  type-level проверки generated-схемы
    fixture-imports.test.ts  проверка alias-импорта JSON вне frontend/
    support/            технические модули scaffold
    browser/            Playwright smoke-тест
  docs/ADR-0001-frontend-toolchain.md
```

Структура соответствует обязательной карте monorepo из
`docs/team/03_FRONTEND.md` §2/§3 и `docs/team/06_EXECUTION_PLAN.md` §3.
Generated-артефакты в `src/api/generated/` создаются из OAS командой
`npm run generate:api` и не редактируются вручную.

## Импорт JSON вне `frontend/`

Alias-и `@fixtures` → `../fixtures` и `@examples` → `../contracts/examples`
настроены в `vite.config.ts` (`resolve.alias` + `server.fs.allow`), а также в
`tsconfig.json` (`paths`). Это позволяет будущим mock-сценариям импортировать
синтетические фикстуры и публичные примеры контракта без копирования внутрь
`frontend/`. Работоспособность подтверждается тестом `tests/fixture-imports.test.ts`.

## Browser-тест и браузерный канал

`npm run test:browser` использует Playwright. В обычной среде браузерный
бинарник Chromium устанавливается отдельно:

```powershell
npx playwright install chromium
```

**Условие текущей среды:** скачивание Chromium из CDN Playwright недоступно
(сетевой таймаут при `npx playwright install chromium`). Поэтому
`playwright.config.ts` запускает тест в системном канале Microsoft Edge
(`channel: 'msedge'`, Chromium-based) — Edge установлен в среде. Если в среде
доступен скачанный Chromium, проект можно вернуть на bundled-браузер, убрав
`channel` из `playwright.config.ts`; для Google Chrome используется
`channel: 'chrome'`. Выбранный для проверки канал указывается в отчёте о
выполнении; сам тест обязан реально проходить в текущей среде.

`playwright.config.ts` запускает preview с явным хостом `--host 127.0.0.1` и
использует тот же хост в `baseURL`. Это обязательно: `vite preview` по
умолчанию слушает только IPv6-loopback `::1`, из-за чего probe Playwright по
`127.0.0.1` получал `connection refused`. Привязка сервера и `baseURL` к одному
адресу делает browser-тест детерминированным при повторных запусках и в CI.

## Проверки (V-C)

Полный набор локальных проверок scaffold:

```powershell
npm ci
npm run generate:api
git diff --exit-code -- src/api/generated
npm run generate:api:check
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:browser
```

Ожидаемый результат: все команды завершаются успешно, `npm run build` создаёт
`frontend/dist/index.html`, unit/component и browser smoke-тесты проходят.
Повторная генерация при неизменном OAS не изменяет `src/api/generated`.
