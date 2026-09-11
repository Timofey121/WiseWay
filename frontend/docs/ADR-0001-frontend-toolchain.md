# ADR-0001. Frontend toolchain WiseWay

- **Статус:** принято (Accepted).
- **Дата:** 11.09.2026.
- **Область:** EPIC E-02, WP-04, leaf LT-04.1a (закрывает техническое решение X-STACK).
- **Связанные документы:** `docs/team/01_PROJECT_TZ.md` §11/§12 (NFR-02), `docs/team/02_API_CONTRACT.md` §1/§12, `docs/team/03_FRONTEND.md` §2/§3, `docs/team/06_EXECUTION_PLAN.md` §2/§3/§7, `contracts/openapi/wiseway-v1.yaml`, `docs/progress/FRONTEND_BACKLOG.md` (E-02/WP-04, LT-04.1a).
- **Граница leaf:** этот ADR и `frontend/package.json` + `frontend/package-lock.json` фиксируют выбор и lock policy. Application scaffold, конфиги, scripts, generated client и mocks — следующие leaf (LT-04.1b, LT-04.2).

## 1. Контекст

ТЗ §11 называет React + TypeScript «рабочей технологической основой для оценки» и прямо указывает, что это **инженерное предложение, а не утверждение об установленных компонентах**; точные версии команда фиксирует в ADR и lock-файлах. NFR-02 требует воспроизводимой сборки из чистой копии с закреплёнными зависимостями. FE §2/§3 задают единую структуру monorepo (`frontend/src/features`, `frontend/src/api/generated`, `frontend/src/mocks`, `frontend/tests`), запрещают ручные DTO и требуют воспроизводимой генерации. API §12 и PLAN §7 требуют генерации клиента из единственного OpenAPI и повторной генерации без diff.

До настоящего решения ни React, ни TypeScript, ни иные инструменты в репозитории **не были установлены**: каталог `frontend/` отсутствовал, product manifest/lock отсутствовали. Настоящий ADR закрывает X-STACK и фиксирует стек. Решение React + TypeScript считается принятым только с момента этого ADR; до него оно не считалось установленным.

Оркестратор уже выбрал допустимые major-версии (CONTEXT leaf LT-04.1a). Конкретные patch-версии выбраны как последние существующие в npm в пределах разрешённых major, с проверкой peer-зависимостей и engines. Точные версии перечислены в разделе 2.

## 2. Решение (точные версии)

Среда исполнения и пакетный менеджер (проверено фактически):

- Node.js: `v24.20.0`; `engines.node: ">=22 <25"`.
- npm: `11.19.0`; `packageManager: "npm@11.19.0"`, `engines.npm: ">=11 <12"`; committed `package-lock.json` (lockfileVersion 3).

### dependencies (runtime)

| Пакет | Версия | Назначение |
|---|---|---|
| `react` | 19.3.0 | UI runtime |
| `react-dom` | 19.3.0 | DOM renderer |
| `openapi-fetch` | 0.14.1 | Типизированный runtime HTTP-клиент, потребляющий типы из generated output |

### devDependencies (build/test/lint/mocks)

| Пакет | Версия | Назначение |
|---|---|---|
| `typescript` | 5.9.3 | Язык; последняя 5.x (typescript-eslint 8.x требует `<6.1.0`) |
| `vite` | 7.3.6 | Dev server и production build; последняя 7.x |
| `@vitejs/plugin-react` | 5.2.0 | React plugin для Vite; peer `vite ^4||^5||^6||^7` |
| `vitest` | 3.2.7 | Unit/component runner; последняя 3.x, поддерживает Vite 7 |
| `jsdom` | 26.1.0 | DOM-окружение для Vitest (stable, engines node >=18, современник Vitest 3) |
| `@testing-library/react` | 16.3.3 | Component-тесты React |
| `@testing-library/jest-dom` | 7.0.1 | DOM-матчеры |
| `@testing-library/dom` | 10.4.1 | Прямая peer-зависимость `@testing-library/react@16` |
| `@playwright/test` | 1.63.0 | Browser/E2E runner (Chromium) |
| `eslint` | 9.39.5 | Lint, flat config; последняя 9.x |
| `typescript-eslint` | 8.70.0 | TS-правила для ESLint 9 (peer eslint ^8.57/^9/^10) |
| `eslint-plugin-react-hooks` | 7.1.1 | Правила hooks (peer eslint ^9) |
| `eslint-plugin-react-refresh` | 0.5.6 | Правила React Refresh (peer eslint ^9) |
| `openapi-typescript` | 7.13.0 | Генерация TS-типов из единственного OAS |
| `ajv` | 8.20.0 | Runtime-валидация mock-запросов/ответов по JSON Schema |
| `ajv-formats` | 3.0.1 | Форматы (`date-time`, `uri`, …) для ajv (peer ajv ^8) |
| `yaml` | 2.9.0 | YAML-парсинг OAS для генератора схем mocks |
| `@types/react` | 19.3.0 | Типы React (peer `@testing-library/react`) |
| `@types/react-dom` | 19.3.0 | Типы React DOM (peer `@testing-library/react`) |
| `@types/node` | 24.13.4 | Типы Node для конфигов/скриптов; ветка, соответствующая Node 24 |

Разделение `dependencies`/`devDependencies`: в production runtime входят только `react`, `react-dom` и `openapi-fetch`. Всё остальное (сборка, типы, тесты, lint, генератор, mock-валидация `ajv`/`ajv-formats`/`yaml`) — инструменты разработки и проверки, поэтому в `devDependencies`. Это согласуется с тем, что mock-контур не является production-поведением.

`scripts` в `package.json` намеренно отсутствует: реальные команды typecheck/lint/component/browser/build добавляются в LT-04.1b.

## 3. Обоснование выбора

- **Node.js 24.x / npm 11.x.** Соответствует фактической среде (`v24.20.0`, `11.19.0`), удовлетворяет engines Vite 7 (`^20.19.0 || >=22.12.0`), Vitest 3 (`>=22.0.0`) и `@testing-library/jest-dom` 7 (`>=22`). npm выбран как единый пакетный менеджер проекта; yarn/pnpm не используются.
- **TypeScript 5.9.3.** Последняя 5.x. Верхняя граница продиктована `typescript-eslint@8` (`>=4.8.4 <6.1.0`), поэтому TypeScript 7.x из реестра несовместим с разрешённым ESLint-стеком.
- **React 19.3.0.** Разрешённая ветка React 19.x; `@testing-library/react@16` поддерживает React `^18||^19`.
- **Vite 7.3.6.** Последняя 7.x. Vite 8 существует, но выходит за разрешённый major.
- **@vitejs/plugin-react 5.2.0.** Последняя 5.x с peer `vite ^7`. `@vitejs/plugin-react@6` требует исключительно `vite ^8`, поэтому несовместим с закреплённым Vite 7.
- **Vitest 3.2.7.** Последняя 3.x; зависит от `vite ^5||^6||^7`, совместима с Vite 7. Vitest 5 существует, но вне разрешённого major.
- **jsdom 26.1.0.** Стабильная ветка, современная Vitest 3, engines `node >=18`. Более новые jsdom (27/30) требуют Node `>=22.22.2`/`^24.15.0`; выбранная ветка снижает риск несовместимости с Vitest 3 при том же runtime.
- **@testing-library/react 16.3.3 + jest-dom 7.0.1 + dom 10.4.1.** `@testing-library/dom` добавлен явно, поскольку в v16 он является peer-зависимостью; без него `npm ls` показал бы unmet peer.
- **@playwright/test 1.63.0.** Разрешённая ветка 1.x; браузерные бинарники устанавливаются отдельной командой (`npx playwright install chromium`) на этапе LT-04.1b, а не в этом leaf.
- **ESLint 9.39.5 + typescript-eslint 8.70.0 + react-hooks 7.1.1 + react-refresh 0.5.6.** Последняя 9.x ESLint и совместимый typescript-eslint 8.x (flat config). ESLint 10 существует, но выходит за разрешённый major; `react-refresh@0.5.6` поддерживает `^9||^10`, `react-hooks@7.1.1` поддерживает `^9`.
- **openapi-typescript 7.13.0 + openapi-fetch 0.14.1.** Разрешённые генератор типов и runtime-клиент; обе библиотеки поддерживают OpenAPI 3.1. `openapi-typescript` объявляет peer `typescript ^5.x`, что согласовано с закреплённым TypeScript 5.9.3.
- **ajv 8.20.0 + ajv-formats 3.0.1 + yaml 2.9.0.** `components.schemas` OAS 3.1 — это JSON Schema 2020-12; ajv 8 валидирует mock payload по этой схеме, `ajv-formats` покрывает форматы, `yaml` разбирает единственный OAS для генератора схем mocks.
- **@types/react 19.3.0, @types/react-dom 19.3.0, @types/node 24.13.4.** Без них TypeScript-проект на React не типизируется, а `@testing-library/react@16` сообщает unmet peer. Это необходимые supporting-зависимости выбранного стека.

## 4. Lock policy

1. `frontend/package-lock.json` **коммитится** и является обязательным артефактом репозитория (lockfileVersion 3).
2. Чистая установка выполняется командой `npm ci` из `frontend/`; `npm ci` требует наличия lock и устанавливает ровно зафиксированное дерево.
3. Версии в `package.json` — точные, без `^`/`~`; `frontend/.npmrc` содержит `save-exact=true`, чтобы новые зависимости добавлялись точными.
4. Изменение lock допустимо только осознанно вместе с изменением `package.json`; тихая пересборка lock не является доказательством готовности.
5. `node_modules/` не коммитится (`frontend/.gitignore`).
6. Секреты в manifest/lock/.npmrc не размещаются.

## 5. Стратегия генерации типов из единственного OAS

- Единственный источник структуры API — `contracts/openapi/wiseway-v1.yaml` (`openapi: 3.1.1`, `info.version: 1.0.0`, 33 `operationId`). Второй контракт не создаётся.
- `openapi-typescript@7.13.0` генерирует TypeScript-типы в `frontend/src/api/generated/` (LT-04.2). `openapi-fetch@0.14.1` предоставляет типизированный runtime-клиент поверх этих типов.
- Generated output не редактируется вручную. Команда генерации документируется и выполняется воспроизводимо; PLAN §7/API §12 требуют повторной генерации **без diff** как доказательства соответствия версии схемы.
- Ручные копии DTO на клиенте запрещены (ТЗ §11, FE §2). Mock-и и real-потребители используют одну и ту же публичную схему.

### 5.1. Реализованная generation-стратегия (LT-04.2)

Решение §5 не меняется; ниже зафиксированы фактические артефакты и команда:

- `npm run generate:api` (скрипт `frontend/scripts/generate-api.mjs`) запускает
  закреплённый `openapi-typescript@7.13.0` против
  `contracts/openapi/wiseway-v1.yaml` и записывает `src/api/generated/schema.ts`,
  затем парсит тот же YAML библиотекой `yaml@2.9.0` и записывает
  `src/api/generated/openapi.json` (JSON OAS для runtime-mocks без YAML-парсера
  в браузере). Оба артефакта — generated-but-versioned и коммитятся.
- `npm run generate:api:check` перегенерирует артефакты во временный каталог и
  сравнивает их с закоммиченными (нормализуя переводы строк), давая машинную
  проверку «повторная генерация без diff» независимо от Git.
- `src/api/generated/client.ts` — тонкая рукописная фабрика
  `createWiseWayClient` на `openapi-fetch@0.14.1` (`createClient<paths>`) с
  настраиваемыми `baseUrl`/`fetch`; ручных DTO и дублирования схем нет.
- Все 33 `operationId` присутствуют в `schema.ts` и `openapi.json`.
- LT-05.1a (WP-05) расширяет ту же генерацию артефактом
  `src/api/generated/operation-meta.ts`: карта `METHOD path` →
  `{ operationId, csrf, idempotencyKey }`, выведенная из наличия `$ref` на
  `#/components/parameters/XCSRFToken` и `#/components/parameters/IdempotencyKey`.
  Артефакт генерируется тем же `npm run generate:api` и проверяется
  `generate:api:check`; решение §5 не меняется.
- LT-05.1b (WP-05) добавляет рукописный `src/api/transport-error.ts` —
  единый `TransportError` для HTTP/сетевых ошибок поверх результатов
  `openapi-fetch`. Решение §5 (генерация типов из единственного OAS, без
  ручных DTO) не меняется: модель не дублирует DTO, а ссылается на
  generated-типы `components['schemas']['FieldError']`/`ErrorCode`. Транспорт
  различает `401 UNAUTHENTICATED` (очистка сессии) и `401 LOGIN_FAILED`
  (ошибка формы без очистки), читая тело через `Response.clone()`.
- LT-05.2a (WP-05) добавляет рукописный `src/api/idempotency.ts` —
  in-memory/session-scoped `IdempotencyStore`, который выдаёт UUID для трёх
  операций с `#/components/parameters/IdempotencyKey` и связывает ключ с
  отпечатком тела (`fingerprintBody`, FNV-1a 64 над стабильной сериализацией).
  Транспорт берёт набор операций из generated `operation-meta.ts` (без
  хардкода), на `2xx`/не-retryable отказе вызывает `complete`, на
  сетевом/`429`/`503` исходе — `retain`; `clearSession()`/`emitUnauthorized()`
  очищают store. Решение §5 не меняется: новых DTO нет, контракт не
  изменяется, состояние ограничено памятью вкладки.
- LT-05.2b (WP-05) добавляет рукописный `src/api/retry.ts` — общую
  retry/backoff policy (`shouldRetry`, `computeRetryDelay`, `createRetryFetch`)
  и single-flight `createPollRegistry`. Решение §5 не меняется: модуль
  ссылается на generated `operation-meta.ts` и `TransportError`, новых DTO и
  правок контракта нет; metadata операции для решения о повторе хранится в
  `WeakMap` (не в заголовках), состояние ограничено памятью вкладки.
  `Retry-After` берётся из уже реализованного `TransportError.retryAfterSeconds`
  (LT-05.1b), poll-интервалы остаются на feature-уровне (app-config).

## 6. Совместимость с OpenAPI 3.1.1

- `openapi-typescript@7.x` поддерживает OpenAPI 3.1 и корректно отображает конструкции 3.1 (`nullable` через union, `oneOf`, `additionalProperties`, `examples`) в TypeScript.
- `openapi-fetch@0.14.x` типизируется от сгенерированных `paths`/`components` и не накладывает собственной модели поверх контракта, поэтому не создаёт ручных DTO и скрытых преобразований ответов.
- Поскольку OAS 3.1 `components.schemas` — это JSON Schema 2020-12, `ajv@8` + `ajv-formats@3` валидируют mock payload по тем же схемам, что использует генератор.
- Совместимость проверена фактически: `npx openapi-typescript contracts/openapi/wiseway-v1.yaml` успешно завершился (exit 0, 124.7 ms, 132 291 байт output), сгенерированный файл содержит пути `/auth/login` и `/sorting/batches`. Вывод выполнялся во временный каталог вне репозитория; в этом leaf generated client не коммитится (LT-04.2).

## 7. Альтернативы

- **Yarn/pnpm** — отклонены: разрешён npm, committed `package-lock.json`.
- **Vite 8 / Vitest 5 / ESLint 10 / @vitejs/plugin-react 6** — отклонены как выходящие за разрешённые major; `plugin-react@6` дополнительно требует Vite 8.
- **Ручные DTO вместо генерации** — отклонены: ТЗ §11/FE §2 запрещают ручные копии моделей.
- **Другой генератор/клиент** — отклонены: разрешены `openapi-typescript` + `openapi-fetch`, обе поддерживают OpenAPI 3.1.

## 8. Последствия и известные ограничения

- Scaffold и generated-артефакты добавлены в LT-04.1b/LT-04.2: `frontend/src`, конфиги, scripts, `src/api/generated/{schema.ts,openapi.json,client.ts}`. Mock-сценарии остаются следующими leaf (WP-06/WP-07) и в этом ADR не описываются.
- `npm audit --omit=dev` — 0 уязвимостей. Полный `npm audit` сообщает 2 moderate в dev-цепочке `@vitest/mocker` (advisory GHSA-82fw-gwwq-j7x9) через Vitest 3.x; исправление требует Vitest 5 (breaking, вне разрешённого решения). Это dev-only и не блокирует leaf.
- npm 11.19.0 сообщает предупреждение о том, что `esbuild@0.28.2` имеет postinstall (`node install.js`), не покрытый allowScripts. Бинарник esbuild фактически присутствует и работает (`npx esbuild --version` → 0.28.2); при более строгой политике scripts в LT-04.1b может потребоваться явное одобрение (`npm install-scripts approve esbuild`).
- npm помечает `eslint@9.39.5` как версию, снятую с поддержки (в реестре уже есть ESLint 10), поскольку выбран разрешённый major 9.x.
