# WiseWay — frontend

Минимальная рабочая основа (scaffold) frontend-приложения WiseWay. Сейчас в
каталоге находятся конфигурация инструментов, точка входа, smoke-тесты,
generated API-артефакты из единственного публичного OAS, базовый
request/session security transport (WP-05) и контрактные mocks
bootstrap/session/config и golden-поиска (WP-06). Продуктовые экраны и
навигация появятся в следующих leaf-задачах (EPIC E-02, WP-07).

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

Из OAS воспроизводимо генерируются три артефакта (все коммитятся):

| Артефакт | Назначение |
|---|---|
| `src/api/generated/schema.ts` | TypeScript-типы всех операций и схем (`openapi-typescript` 7). Импорт: `import type { paths, components, operations } from '@/api/generated/schema'`. |
| `src/api/generated/openapi.json` | Тот же OAS, сконвертированный YAML → JSON; используется runtime-mocks (WP-06/WP-07), которым не нужен YAML-парсер в браузере. |
| `src/api/generated/operation-meta.ts` | Карта `METHOD path` → `{ operationId, csrf, idempotencyKey }`, выведенная из OAS. Используется транспортом, чтобы ставить CSRF/Idempotency-Key только объявленным операциям. |

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

`schema.ts`, `openapi.json` и `operation-meta.ts` генерируются целиком и не
редактируются вручную: изменения будут перезаписаны следующей генерацией.
Обоснование выбора генератора и клиента — в
[ADR-0001](docs/ADR-0001-frontend-toolchain.md) §5.

## Безопасный HTTP-транспорт

Единый клиент для real- и mock-режимов создаётся фабрикой
`createApiClient` из `src/api/transport.ts`:

```ts
import { createApiClient } from '@/api/transport'
import { setCsrfToken, clearSession } from '@/api/session-context'

const api = createApiClient({ mode: 'real' }) // baseUrl по умолчанию — '/api/v1'

const { data } = await api.GET('/session')
setCsrfToken(data.csrf_token) // CSRF-токен живёт только в памяти вкладки
```

Что гарантирует транспорт (по `contracts/openapi/wiseway-v1.yaml` и API §2):

- в `real`-режиме запросы идут с `credentials: 'include'` — HttpOnly cookie
  `wiseway_session` обслуживает браузер; frontend её не читает и не хранит;
- каждый запрос идёт с `cache: 'no-store'`;
- `X-CSRF-Token` ставится только 10 операциям, объявившим
  `#/components/parameters/XCSRFToken`, и только при наличии токена
  (провайдер `csrfTokenProvider` или in-memory `session-context`);
- `Idempotency-Key` ставится только 3 операциям с
  `#/components/parameters/IdempotencyKey` (`publishDictionary`,
  `createSortingBatch`, `returnQuarantineItem`). Ключ выдаёт in-memory
  `idempotencyStore` и связывает его с телом запроса: повтор того же тела
  сохраняет ключ, изменённое тело получает новый. Остальным операциям
  фиктивный ключ не подставляется;
- CSRF и ключ идут только в заголовках, не в теле;
- retry/backoff (`src/api/retry.ts`) применяется поверх base-fetch: при
  сетевом сбое/`429`/`503` повторяются только безопасные чтения (GET и
  читающие POST) и три идемпотентные операции. Неидемпотентные мутации и
  `login`/`logout` не повторяются автоматически. Повтор отправляет тот же
  `Request` (то же тело и тот же `Idempotency-Key`);
- `X-Request-ID` ответа передаётся в `onRequestId`;
- ответ `401` с кодом `UNAUTHENTICATED` очищает `session-context` и уведомляет
  подписчиков `onUnauthorized`; `401` с кодом `LOGIN_FAILED` остаётся ошибкой
  формы входа и **не** очищает сессию; `403` не повторяется автоматически.

`src/api/session-context.ts` — in-memory держатель CSRF-токена: без
`localStorage`, `sessionStorage`, cookie и URL; токен меняется при новом входе
и очищается при logout/`UNAUTHENTICATED`. Секреты и тела запросов не логируются.

### Идемпотентность publish/batch/return

`src/api/idempotency.ts` хранит in-memory состояние идемпотентности трёх
операций, объявленных в OAS с `Idempotency-Key` (набор берётся из generated
`operation-meta.ts`, список не хардкодится). Для каждой операции/ресурса
(стабильный `scope`, например `dictionary_id`) держится одна ожидающая запись
`{ key, bodyFingerprint }`:

- `begin(operationId, body, scope?)` возвращает прежний UUID, если тело не
  изменилось (retry/lost response/double submit), и новый — если тело
  изменилось (новое явное действие) или записи нет. Ключ никогда не уходит с
  другим телом;
- `complete(operationId, scope?)` вызывается транспортом на `2xx` и на
  окончательном не-retryable отказе: следующее действие получит новый ключ;
- `retain(operationId, scope?)` вызывается на сетевом сбое и `429`/`503`:
  ожидающая запись сохраняется, повтор отправляет тот же ключ и тело;
- `clear()` очищает всё состояние. `clearSession()`/`emitUnauthorized()`
  (`session-context`) вызывают её — logout/401/смена пользователя не оставляют
  чужой контекст.

Хранятся только UUID и детерминированный отпечаток тела (`fingerprintBody`,
FNV-1a 64 над стабильной сериализацией); сами тела и секреты не сохраняются и не
логируются. Состояние ограничено сессией вкладки: без `localStorage`,
`sessionStorage`, cookie и URL. Транспорт использует session-scoped
`defaultIdempotencyStore`, если не передан собственный `idempotencyStore`;
`createIdempotencyStore()` создаёт изолированный экземпляр для тестов. Явный
`idempotencyKeyProvider` имеет приоритет над store и не управляет жизненным
циклом ключа.

```ts
import { createApiClient } from '@/api/transport'
import { createIdempotencyStore } from '@/api/idempotency'

const api = createApiClient({
  mode: 'real',
  idempotencyStore: createIdempotencyStore(), // необязательно: по умолчанию session-scoped store
})
```

### Retry/backoff и single-flight polls

`src/api/retry.ts` — общая политика безопасного повтора (API §2/§11, SEM
«Повторы», TZ §12). Транспорт использует её автоматически; настраивается через
`retry`/`sleep`/`now` фабрики `createApiClient`:

```ts
const api = createApiClient({
  mode: 'real',
  retry: { maxAttempts: 3, baseDelayMs: 500, maxDelayMs: 8000, jitter: true },
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)), // можно подменить в тестах
  now: () => Date.now(),
})
```

- `shouldRetry(error, operationMeta)` разрешает повтор только для безопасных
  чтений (`GET`/читающие POST) и трёх идемпотентных операций. Все прочие
  мутации (`createDictionary`, `replaceDictionaryDraft`,
  `restoreDictionaryDraft`, `createDictionarySimulation`,
  `createSortingSelection`, `createSortingPreview`, `logout`) и `login` не
  повторяются никогда; окончательные не-retryable ошибки тоже.
- `computeRetryDelay(error, attempt, config)`: `Retry-After` (delta-seconds) из
  `TransportError.retryAfterSeconds` имеет приоритет и ограничивается сверху
  `maxDelayMs`; иначе — экспоненциальный backoff с тем же cap и опциональным
  jitter.
- `createRetryFetch(baseFetch, options)` повторяет тот же `Request` (тело и
  `Idempotency-Key`), используя `request.clone()`. Metadata операции для
  решения о повторе транспортируется через module-level `WeakMap`, а не через
  заголовки. После исчерпания попыток сетевая ошибка пробрасывается, а
  HTTP-ответ возвращается без изменений.
- `createPollRegistry()` — single-flight коалесцинг: пока poll-запрос по ключу
  в полёте, повторный `run(key, fn)` получает тот же promise и не создаёт
  второй запрос; после завершения новый вызов запускает новый. Состояние
  только в памяти; `clear()`/session cleanup его сбрасывают.

`defaultRetryConfig` — 3 попытки, базовая задержка 500 мс, cap 8 с, jitter.
Poll-интервалы (1 с для batch, 30 с для журнала) берутся из app-config на
feature-уровне: этот модуль даёт только примитив, без хардкода интервалов.
Session-scoped `defaultPollRegistry` очищается `clearSession()`/
`emitUnauthorized()` вместе с CSRF и `Idempotency-Key`.

### Единая безопасная модель ошибок

`src/api/transport-error.ts` приводит и HTTP-ошибки, и сетевые сбои
`openapi-fetch` к одному типу `TransportError`. Он доступен и через
`src/api/transport.ts`:

```ts
import { createApiClient, throwIfError, isTransportError } from '@/api/transport'

const api = createApiClient({ mode: 'real' })
try {
  const data = throwIfError(await api.GET('/session'))
} catch (error) {
  if (isTransportError(error)) {
    // error.code, error.message, error.requestId, error.operationId,
    // error.fieldErrors, error.retryable, error.retryAfterSeconds
  }
}
```

`TransportError` содержит только безопасные metadata публичного контракта:

| Поле | Источник |
|---|---|
| `kind` | `'http'` для ответа сервера, `'network'` для сбоя/таймаута |
| `status` | HTTP-статус; `null` для сети |
| `code` | `error.code` из контракта; при отсутствии/битом теле — безопасный код по статусу |
| `message` | безопасное русское пользовательское сообщение (`error.message` либо справочник) |
| `requestId` | `error.request_id` либо `X-Request-ID` |
| `operationId` | `error.operation_id` (`null`, если операция не создавалась) |
| `retryable` | `error.retryable`; иначе по таблице API §11 (429/503/сеть — `true`) |
| `fieldErrors` | `error.field_errors` (`#/components/schemas/FieldError`) |
| `retryAfterSeconds` | `Retry-After` в секундах (delta-seconds), иначе `null` |

Гарантии безопасности:

- сырое тело ответа, пароль, поисковый текст, физические пути, стек и текст
  исключения никогда не попадают в `TransportError`;
- при отсутствии/битом теле код синтезируется по статусу
  (`401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 INVALID_STATE`,
  `422 VALIDATION_ERROR`, `429 RATE_LIMITED`, `500 INTERNAL_ERROR`,
  `503 SERVICE_UNAVAILABLE`), а сообщение берётся из безопасного справочника;
- сетевой сбой даёт `kind: 'network'`, `code: 'NETWORK_ERROR'`,
  `retryable: true` и не превращается в success;
- `throwIfError` определяет успех по `response.ok`, поэтому `200/204` не
  становится ошибкой, а ошибочный ответ без тела — ложным успехом.

`mode` меняет только transport config: `real` использует переданный/глобальный
`fetch` c cookie credentials, `mock` — обязательный переданный mock-fetch
(handlers подключают WP-06/WP-07). Схемы запросов/ответов общие.

## Mock-режим bootstrap/session/config (LT-06.1)

`src/mocks/` — контрактные mocks без backend для операций
`getHealth`, `login`, `getSession`, `logout`, `getAppConfig`, `listRoots`,
`listCompanies` и golden-поиска `searchFiles`/`getSearchFacet` (см. раздел
«Mock search handlers»). Ответы bootstrap берутся из публичных примеров
`contracts/examples/**` (индексируются по `fixtures/synthetic/manifest.json`),
а не из ручных копий DTO, и валидируются по схемам единственного OAS.

```ts
import { createApiClient } from '@/api/transport'
import { createMockFetch, MockController } from '@/mocks'

const controller = new MockController()
const api = createApiClient({
  mode: 'mock',
  baseUrl: 'http://localhost/api/v1', // в браузере достаточно '/api/v1'
  fetch: createMockFetch(controller),
})

const health = await api.GET('/health') // 200 {status: 'ok'}
```

`createMockFetch(controller?)` — fetch-совместимый перехватчик; контроллер
можно не передавать (будет создан свой). `MOCK_MODE`/`MOCK_MARKER_HEADER`
(`X-WiseWay-Mock`) экспортируются из `@/mocks` как явный маркер mock-ответа.

### Сценарии

`MockController` управляет воспроизводимым состоянием:

| Метод | Действие |
|---|---|
| `setDelayMs(ms)` | управляемая задержка ответа; ожидание инъектируется через `new MockController({ sleep })`, поэтому тесты не ждут реально |
| `setConfigProfile('n100' \| 'n10')` | профиль `app-config`: `search_result_limit` 100 или 10 |
| `setSearchFreshnessProfile('CURRENT' \| 'UPDATING' \| 'STALE')` | freshness-профиль golden-ответов `/search` (по умолчанию `CURRENT`) |
| `setRootsEmpty(true)` | `listRoots` → `roots-empty` (пустой `items`) |
| `setCompaniesEmpty(true)` | `listCompanies` → `companies-empty` (пустой `items`) |
| `reset()` | очищает mock-сессию, задержку, профиль, freshness и empty-переопределения (freshness → `CURRENT`) |

Сессия создаётся успешным `login` по одному из synthetic-примеров
(`login-request-worker-one/two/admin`) и очищается `logout`. `getSession`,
`getAppConfig`, `listRoots`, `listCompanies` без сессии дают
`401 UNAUTHENTICATED`; `logout` без/с неверным `X-CSRF-Token` — `403 CSRF_FAILED`.
Неизвестный маршрут даёт безопасную `404 NOT_FOUND`, а не правдоподобный успех.
Все ответы несут `X-Request-ID`, пользовательские — `Cache-Control: no-store`.

Невалидное тело `login` (лишнее поле, отсутствие `password`, пустой/битый JSON)
отклоняется до успеха: `422 VALIDATION_ERROR` с безопасными `field_errors` по
схеме `LoginRequest`. Валидация выполняется `ajv@8` (`ajv/dist/2020`, JSON
Schema 2020-12) + `ajv-formats` по `src/api/generated/openapi.json`; схемы
вручную не копируются.

**Границы:** mock — не защищённый auth backend. Он не проверяет реальные
credentials, не устанавливает cookie и не хранит серверные сессии; пароли в
примерах — инертные placeholder'ы, которые не логируются и не возвращаются.
CSRF-проверка в mock — воспроизведение контрактного поведения, не
доказательство безопасности сервера. Mock-прохождение не является real-backend
evidence.

Проверки сценариев: `npm run test` (файл `tests/mocks/bootstrap.test.ts`).

## Mock search foundation (LT-06.2a-i)

`src/mocks/search/` — golden data foundation для HTTP-handlers
`searchFiles`/`getSearchFacet` (LT-06.2a-ii, см. следующий раздел).

- `corpus.ts` — детерминированный materializer
  `fixtures/synthetic/corpus.json`: раскрывает `files[]` и `cohorts[]` (только
  literal `{index}`/`index_pad`, без поиска) в полные schema-valid
  `SearchItem` и строит контекстный каталог `Marker` из
  `marker_model.contexts`. `marker_id` = `marker-<root_id>-<value_id>-…`;
  `display_path` = `<root.display_prefix>/<relative_path>` (или явный из
  корпуса); `filename` — basename. `SearchItem.markers` содержит только
  распознанные VALUE-родителей; терминальный UNRECOGNIZED-маркер отклонения
  доступен отдельно (`getUnrecognizedMarker`) и входит в каталог/фасеты.
- `expectations.ts` — загрузчик golden
  `fixtures/synthetic/search_expectations.json` (51 search + 6 facet) и
  literal-resolver `resolveSearchScenario(request, { freshnessProfile? })` /
  `resolveFacetScenario(request)`. Ответ — полный schema-valid
  `SearchResponse`/`FacetResponse`; `request_state_id` эхо исходного запроса;
  `items` — из materialized-инвентаря по `expected.item_ids` в заданном
  порядке; `next_facet`/facet options обогащаются `raw_value`/`display_value`/
  `kind` из каталога; freshness — профиль CURRENT по умолчанию (UPDATING/STALE
  выбираются явно). Если сценарий не найден — `undefined`; matcher, ranking и
  парсинг путей отсутствуют, вычисленного fallback нет.

Проверки: `tests/mocks/search-foundation.test.ts` — 57 golden-сценариев
разрешаются в schema-valid ответы с literal totals/order/`item_ids`/facets,
cohort раскрыт, UNRECOGNIZED-отклонения и freshness-профили воспроизводимы,
неизвестный request даёт `undefined`.

## Mock search handlers (LT-06.2a-ii)

`POST /api/v1/search` (`searchFiles`) и `POST /api/v1/search/facet`
(`getSearchFacet`) подключены к mock-fetch через `src/mocks/handlers/search.ts`
и зарегистрированы в `src/mocks/handlers/index.ts`. HTTP-слой только
маршрутизирует и валидирует; literal-ответ формирует foundation
`src/mocks/search/`:

- требуется активная mock-сессия: без неё оба метода отвечают
  `401 UNAUTHENTICATED`;
- тело проверяется по схемам OAS `SearchRequest`/`FacetRequest` (ajv): лишнее
  или отсутствующее поле, пустое/битое JSON-тело → `422 VALIDATION_ERROR` с
  безопасными `field_errors` и без успеха;
- валидный, но не объявленный в golden сценарий → объявленная контрактом
  `400 INVALID_QUERY` с безопасным сообщением (matcher/ranking не выполняются и
  правдоподобный успех не выдумывается);
- найденный сценарий → полный `SearchResponse`/`FacetResponse` из foundation:
  literal totals/order/items/next_facet, `index_generation`/
  `schema_set_version`/`ranking_profile_version` из корня и
  `request_state_id` — точное эхо исходной отправки;
- freshness-профиль (`CURRENT`/`UPDATING`/`STALE`) задаётся
  `MockController.setSearchFreshnessProfile` и отражается в ответе; `reset()`
  возвращает `CURRENT`;
- поиск — чтение (`csrf: false`, `idempotencyKey: false`): он не несёт
  `X-CSRF-Token`/`Idempotency-Key` и не инициирует mutation/batch запросов;
- ответы несут `X-Request-ID`, `Cache-Control: no-store` и mock-маркер
  `X-WiseWay-Mock`.

Проверки: `tests/mocks/search-handlers.test.ts` — IDLE/zero/limited (N=10)/
RESULTS/UNRECOGNIZED/freshness через HTTP-слой с literal golden значениями,
facet-переоткрытие уровня, echo `request_state_id`, invalid/unknown → ошибка,
без сессии → 401, отсутствие иных запросов.

## Mock search delay/error/race (LT-06.2b)

`MockController` управляет воспроизводимыми сценариями поиска раздельно по
двум независимым request scope: `search` — основная таблица (`searchFiles`),
`facet` — выпадающий список уровня (`getSearchFacet`). Поздний ответ одного
scope не влияет на другой; `request_state_id` каждого ответа — точное эхо
конкретной отправки.

| Метод | Действие |
|---|---|
| `setScopeDelay('search' \| 'facet', ms)` | базовая задержка отдельного scope; `search` и `facet` независимы |
| `getScopeDelay(scope)` | текущая задержка scope |
| `setSendDelays(scope, [ms, …])` | очередь per-send задержек: каждая следующая отправка scope берёт следующее значение; после исчерпания действует `setScopeDelay` |
| `enqueueSendDelay(scope, ms)` | добавить одно per-send значение в конец очереди |
| `getPendingSendDelays(scope)` | остаток очереди (копия) |
| `failNext('searchFiles' \| 'getSearchFacet', code)` | одноразовая объявленная ошибка следующей отправки операции |
| `setError(operation, code)` | постоянная объявленная ошибка до `clearError`/`reset` |
| `clearError(operation)` | снять и постоянную, и одноразовые ошибки операции |
| `reset()` | очищает сессию, задержки, очереди, ошибки, профиль, freshness и empty-переопределения |

Задержка применяется до нормального lookup handler-а и инъектируется через
`sleep` (`new MockController({ sleep })`), поэтому тесты не ждут реально и
управляют порядком через controlled clock. Per-send очередь позволяет
детерминированно воспроизвести нужный порядок ответов (race): mock не «решает»
гонку, а лишь отдаёт ответы в заданном порядке, чтобы UI-потребитель мог
проверить собственную логику последнего запроса.

Коды ошибок ограничены объявленными контрактом (`declaredSearchErrors` из
`@/mocks`): `INVALID_QUERY` (400), `VALIDATION_ERROR`/`INVALID_MARKER_SELECTION`
(422), `SCHEMA_VERSION_CHANGED`/`ROOT_NOT_READY` (409), `RATE_LIMITED` (429),
`SEARCH_UNAVAILABLE` (503), `INTERNAL_ERROR` (500). Тело и `retryable` берутся
из примеров `contracts/examples/errors/*.json`; выдуманных кодов и
правдоподобного успеха вместо ошибки нет. Невалидный запрос по-прежнему даёт
`422 VALIDATION_ERROR` до применения управляемой ошибки, валидный, но не
объявленный — `400 INVALID_QUERY`.

Через транспорт `503 SEARCH_UNAVAILABLE` (`retryable: true`) автоматически
повторяется: в тестах используется `retry: { maxAttempts: 1 }` либо
учитывается число попыток.

Проверки: `tests/mocks/search-error-race.test.ts` — независимость scope-задержек,
воспроизводимость каждой объявленной ошибки, одноразовость `failNext`,
постоянство `setError`, очистка `reset()`, детерминированный порядок двух
отправок, точный `request_state_id` и invalid request без успеха.

## Структура

```text
frontend/
  index.html
  scripts/
    generate-api.mjs          генерация schema.ts + openapi.json + operation-meta.ts
    check-generated.mjs       проверка повторной генерации без diff
  src/
    main.tsx            точка входа React
    App.tsx             минимальный placeholder (без экранов продукта)
    features/{auth,search,dictionaries,sorting,quarantine,audit}/
    api/
      generated/        generated-артефакты (schema.ts, openapi.json,
                        operation-meta.ts) и client.ts
      session-context.ts  in-memory CSRF/401-состояние и session-scope очистка
      idempotency.ts      in-memory Idempotency-Key для publish/batch/return
      retry.ts            retry/backoff policy и single-flight poll registry
      transport-error.ts  TransportError и безопасный разбор ошибок
      transport.ts        createApiClient: credentials/no-store/CSRF/idempotency/retry
    mocks/              schema-valid mocks bootstrap/session/config и golden-поиска (WP-06)
      index.ts          createMockFetch, MockController, MOCK_MODE
      router.ts         разбор Request и диспетчеризация; неизвестный → 404
      validate.ts       ajv-валидация запросов по generated openapi.json
      data.ts           загрузка contracts/examples через @examples + manifest
      controller.ts     delay/profile/freshness/empty/session + search
                        scope-delay/error/queue/reset
      responses.ts      контрактные заголовки и ErrorResponse
      handlers/         health, login, getSession, logout, appConfig, roots,
                        companies, search (searchFiles/getSearchFacet)
      search/           golden search/facet foundation (LT-06.2a-i)
        corpus.ts       materializer corpus.json → SearchItem/Marker
        expectations.ts literal-resolver search_expectations.json
        errors.ts       объявленные контрактом ошибки поиска (LT-06.2b)
  tests/
    App.test.tsx        component smoke-тест
    api/client.test.ts  runtime-проверки запросов клиента A/B/C
    api/transport.test.ts  состав Request, CSRF/Idempotency/401/403/request_id
    api/idempotency.test.ts  key/body lifecycle, retry/complete, session cleanup
    api/retry.test.ts   shouldRetry/backoff, same-Request retry, no-parallel-poll
    api/transport-error.test.ts  HTTP/network-ошибки и отсутствие утечек
    api/generated-types.test.ts  type-level проверки generated-схемы
    mocks/bootstrap.test.ts  bootstrap/session/config mocks и их состояния
    mocks/search-foundation.test.ts  golden search/facet foundation
    mocks/search-handlers.test.ts  HTTP-handlers searchFiles/getSearchFacet
    mocks/search-error-race.test.ts  delay/error/race управление поиском
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
