# WiseWay — frontend

Минимальная рабочая основа (scaffold) frontend-приложения WiseWay. Сейчас в
каталоге находятся конфигурация инструментов, точка входа, smoke-тесты,
generated API-артефакты из единственного публичного OAS, базовый
request/session security transport (WP-05) и контрактные mocks
bootstrap/session/config, golden-поиска (WP-06) и
targets/dictionaries/симуляции/публикации/очереди/выбора/preview/партий (WP-07,
LT-07.1a/LT-07.1b/LT-07.1c/LT-07.2a/LT-07.2b/LT-07.2c) и карантина/возврата
(LT-07.3a).
Продуктовые экраны появятся в следующих leaf-задачах; русская оболочка с
навигацией по разделам добавлена в LT-08.1, а app-level клиент с переключателем
real/mock, контейнер сессии, загрузка `app-config` и единые форматы —
в LT-08.2 (EPIC E-03, WP-08).

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

## Оболочка и навигация разделов (LT-08.1)

`src/App.tsx` рендерит `AppShell` из `src/app/`. Оболочка состоит из заголовка
`WiseWay`, навигации по разделам и области содержимого. Разделы идут строго в
порядке ТЗ §4 и не содержат лишних функций/dashboard:

1. «Поиск» — стартовый раздел;
2. «Справочники»;
3. «Очередь сортировки»;
4. «Карантин»;
5. «Журнал».

Навигация — `<nav aria-label="Разделы приложения">` с нативными `<button>`;
активный раздел отмечен `aria-current="page"` и выделен не только цветом.
Управление доступно мышью и клавиатурой: `Tab` доходит до каждого раздела,
`Enter`/`Space` активируют, фокус обозначен видимым `:focus-visible` контуром
(NFR-01). Все пользовательские подписи — на русском.

Ещё не реализованные разделы показывают честную заглушку «Раздел ещё не
реализован» с описанием будущего содержимого и не изображают рабочий продукт
(без выдуманных результатов, итогов и счётчиков). Логика поиска, справочников,
очереди, карантина и журнала в этот leaf не входит.

### Память вместо URL и storage

Активный раздел хранится только в состоянии React текущей вкладки. Переход
между разделами:

- не выполняет сетевых запросов (ни `fetch`, ни `XMLHttpRequest`);
- не пишет в `location`/URL, `history.state`, `localStorage`,
  `sessionStorage` и cookie.

Перезагрузка или закрытие вкладки очищают состояние, потому что оно нигде не
персистится. Это соответствует SRCH-18 и FE §4: поиск при переходах живёт
только в памяти вкладки.

### Реестр сброса приватного состояния

`src/app/private-state-registry.ts` — общий модульный in-memory реестр, которым
пользуются последующие листья (logout/истечение сессии/смена пользователя):

```ts
import {
  registerPrivateStateReset,
  resetPrivateState,
} from '@/app/index'

const unsubscribe = registerPrivateStateReset(() => {
  // очистить приватное состояние: поиск, списки, выбранные файлы и т. п.
})

resetPrivateState() // вызовет все зарегистрированные сбросы ровно один раз
unsubscribe() // после этого сброс больше не вызывается
```

Гарантии: `resetPrivateState()` вызывает каждую зарегистрированную функцию ровно
один раз за вызов; исключение внутри одного сброса не мешает остальным; снятые
подписки не вызываются; реестр не выполняет сетевых запросов и ничего не
персистит. Сам `AppShell` в реестр не регистрируется — это оставлено
auth/session-листу (LT-09.2).

> Примечание для Windows: из-за регистронезависимой файловой системы импорт
> `@/app` может конфликтовать с `src/App.tsx`. В коде используется явный путь
> `@/app/index` (и `./app/index` из `App.tsx`).

## App API-клиент, сессия и app-config (LT-08.2)

### Переключатель транспорта real/mock

`src/app/app-api.ts` — единственная app-level фабрика клиента:

```ts
import { createAppApiClient } from '@/app/index'

const api = createAppApiClient()
```

Режим выбирается на этапе сборки по `import.meta.env.VITE_API_MODE`:

- точное значение `mock` → `createApiClient({ mode: 'mock', fetch: createMockFetch() })`;
- любое другое значение, включая отсутствие переменной, → `createApiClient({ mode: 'real' })`.

Молчаливого отката в mock нет: опечатка/пустое значение означает `real`.
Переменная не задана по умолчанию, поэтому dev/build работают в `real`-режиме.
Для mock-демонстрации: `VITE_API_MODE=mock npm run dev`. UI-компоненты не
создают транспорт напрямую — клиент передаётся через `AppConfigProvider`
(далее — через app-level провайдеры).

### Присутствие сессии

`src/app/session-state.ts` — минимальный in-memory контейнер
`anonymous | authenticated` (`getSessionStatus`, `subscribeSessionStatus`,
`markAuthenticated`, `markAnonymous`, `resetSessionState`). Он не хранит
токены и учётные данные (CSRF остаётся в `src/api/session-context.ts`), ничего
не персистит и не делает запросов. Контейнер зарегистрирован в общем реестре
LT-08.1, поэтому `resetPrivateState()` возвращает его в `anonymous`. Драйвером
будет LT-09.1 (login/session/logout).

### Загрузка app-config без выдуманных значений

`src/app/app-config-context.tsx` (`AppConfigProvider`, `useAppConfig`) и
`src/app/app-config-store.ts` загружают `GET /app-config` **только** при
`authenticated`-сессии. Пока пользователь анонимен, состояние — `idle` и
запросов нет (ложный `401` не провоцируется).

Состояния: `idle`, `loading`, `ready`, `error`. Пределы, TTL, poll-интервалы и
`display_timezone` не хардкодятся и не подставляются по умолчанию: они
приходят только из ответа сервера. При ошибке сохраняется безопасное русское
сообщение, доступен безопасный `request_id` и кнопка «Повторить»; `config`
остаётся `null`, выдуманные пределы/пояс не используются. Поздний ответ
устаревшего запроса игнорируется, а `resetPrivateState()`/logout очищают
конфигурацию и возвращают провайдер в `idle`.

```tsx
import {
  AppConfigProvider,
  createAppApiClient,
  useAppConfig,
} from '@/app/index'

function Screen() {
  const { status, config, error, reload } = useAppConfig()
  // config.display_timezone / config.search_result_limit / config.max_batch_items
  // и остальные поля берутся только из ответа сервера.
  return null
}

const api = createAppApiClient() // единственное место создания транспорта

<AppConfigProvider client={api}>
  <Screen />
</AppConfigProvider>
```

## Единые форматы (дата/размер/количество)

`src/shared/format.ts` — чистые функции без React и без хардкода timezone
(FE §4, Q-042):

| Функция | Контракт |
|---|---|
| `formatDateTime(instant, timeZone)` | `ДД.ММ.ГГГГ ЧЧ:ММ` в заданном IANA-поясе, без секунд и суффикса зоны; используются явные числовые части `Intl.DateTimeFormat`, а строка собирается вручную |
| `formatSize(bytes)` | десятичные B/KB/MB/GB/TB с делителем 1000, максимум один дробный знак (точка, как в golden Q-042: `1.5 KB`, `4.1 KB`); единицы остаются латиницей |
| `formatCount(count)` | точное целое без научной нотации и разделителей групп |

`display_timezone` всегда передаётся из `AppConfig`; значение по умолчанию не
подставляется. Единица размера выбирается по величине, затем значение
округляется до одного знака (`999999 B → 1000 KB`, `1000000 B → 1 MB`).
Невалидный вход (битая дата, неизвестный пояс, `NaN`, `±Infinity`,
отрицательный размер) даёт нейтральный прочерк `—`.

Форматтеры размера и даты кросс-проверяются тестом против независимого
golden-корпуса `fixtures/synthetic/search_expectations.json` (`format_samples`,
Q-042): каждый `size`/`date` пример должен совпасть с literal-значением
фикстуры.

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

## Mock targets/dictionaries (LT-07.1a)

`src/mocks/handlers/targets.ts` и `src/mocks/handlers/dictionaries.ts`
подключают к mock-fetch шесть операций WP-07 без backend и filesystem:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `GET /companies/{company_id}/target-directories` | 200 `PageTargetDirectory` | finite-страница allowlist компании, `prefix`/`cursor`/`limit` |
| `POST /companies/{company_id}/target-directories/resolve` | 200 `TargetDirectory` | разрешает synthetic `display_path`; каталоги не создаются |
| `GET /companies/{company_id}/dictionaries` | 200 `DictionaryListResponse` | company-scoped |
| `POST /companies/{company_id}/dictionaries` | 201 `Dictionary` | пустой черновик `draft_revision=0`; CSRF обязателен |
| `GET /dictionaries/{dictionary_id}` | 200 `Dictionary` | неизвестный → 404 `NOT_FOUND` |
| `PUT /dictionaries/{dictionary_id}/draft` | 200 `Dictionary` | атомарная замена, `draft_revision+1`; CSRF обязателен |

- Allowlist целей и его `display_path` берутся из literal-фикстуры
  `fixtures/synthetic/rule_expectations.json` (`target_directories` +
  `target_display_prefix`). `resolve` ищет только настроенную цель компании:
  несуществующий каталог и цель другой компании → 422 `INVALID_TARGET`,
  путь вне `DEMO:/SandboxRoot/` → 422 `PATH_OUTSIDE_ROOT`, малформед
  `relative_directory` → 422 `VALIDATION_ERROR`. Файлового доступа и
  создания каталогов нет.
- Store справочников (`src/mocks/dictionaries/store.ts`) — in-memory,
  session-scoped, seed из `contracts/examples/dictionaries/*`
  (`dictionary-atlas-general`, `dictionary-atlas-invoices`,
  `dictionary-nova-general`). Уникальность имени — внутри компании после
  `trim` + casefold; конфликт → 409 `DICTIONARY_NAME_CONFLICT`. `reset()`
  восстанавливает seed.
- `replaceDictionaryDraft` сохраняет переданные имя/описание/правила и
  увеличивает `draft_revision`; несовпадение `expected_draft_revision` → 409
  `DRAFT_VERSION_CONFLICT` без частичной записи. `Rule` валидируется по схеме
  OAS (priority 1–1000, `match_field`, mask 1–512 без `**`, `target_stem`
  1–200), `rule_id` уникальны, а `target` должен входить в allowlist компании
  (иначе 422 `INVALID_TARGET`). Matcher, publish/restore и файловые действия
  отсутствуют.
- GET-операции требуют только активной mock-сессии (без неё 401
  `UNAUTHENTICATED`). POST/PUT проходят общий guard
  `requireSessionAndCsrf` (тот же, что и `logout`): без/с неверным
  `X-CSRF-Token` → 403 `CSRF_FAILED` без изменения store.
- Тела валидируются по схемам OAS до успеха: лишнее поле, отсутствующее поле,
  пустое/битое JSON-тело → 422 `VALIDATION_ERROR`. Ответы несут
  `X-Request-ID`, `Cache-Control: no-store` и маркер `X-WiseWay-Mock`.
- `MockController` управляет объявленными ошибками targets/dictionaries:
  `setError(operation, code)` / `failNext(operation, code)` / `clearError` /
  `consumeDictionaryError`. Коды ограничены объявленными контрактом
  (`declaredDictionaryErrors` из `@/mocks`): `INVALID_TARGET`,
  `PATH_OUTSIDE_ROOT`, `DICTIONARY_NAME_CONFLICT`, `DRAFT_VERSION_CONFLICT`,
  `VALIDATION_ERROR`. Тело/статус берутся из
  `contracts/examples/errors/*.json`.

Проверки: `tests/mocks/dictionaries-draft.test.ts` — targets list/resolve
valid/invalid/outside, company-scope и пагинация, list/get/create/replace
dictionaries, name- и revision-conflict, границы `Rule` и `CreateDictionary`,
401/403/404/422, управляемые ошибки и `reset()`.

## Mock simulations (LT-07.1b)

`src/mocks/handlers/simulations.ts` подключает к mock-fetch две операции WP-07
без backend, matcher и файловых действий:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /dictionaries/{dictionary_id}/simulate` | 201 `Simulation` | canned-сценарий, первая страница; CSRF обязателен |
| `GET /simulations/{simulation_id}` | 200 `Simulation` | очередная страница `rows`; `cursor`/`limit` |

- Данные берутся из публичных примеров
  `contracts/examples/simulations/*.json`
  (`simulation-atlas-full-page1/page2`, `empty`, `conflict`, `same-target`,
  `v3-restored`) через `src/mocks/simulations/store.ts`. План, matcher,
  ranking, RuleSet и READY-набор не вычисляются: store лишь хранит literal
  canned-сценарии и отдаёт объявленные страницы.
- Сценарий выбирает `MockController.setSimulationScenario('full' | 'empty' |
  'conflict' | 'same-target' | 'no-scenario')` (по умолчанию `full`). Каждый
  сценарий — изолированный универсум со своей `draft_revision`,
  `base_rule_set` и `ready_snapshot_id`. `no-scenario` использует пример
  `simulation-atlas-v3-restored` (наибольший `counts.no_scenario`).
- `createDictionarySimulation` требует сессию и корректный `X-CSRF-Token`
  (общий guard `requireSessionAndCsrf`), валидирует `CreateSimulationRequest`
  по схеме OAS, проверяет существование справочника (иначе 404) и
  `expected_draft_revision` против ТЕКУЩЕЙ ревизии `DictionaryStore` (той же,
  что возвращает `GET /dictionary`); несовпадение → 409
  `DRAFT_VERSION_CONFLICT` (OAS `DraftVersionConflict`, literal-фикстура
  `simulate-stale-draft`). Успех — 201 `Simulation` первой страницы: plan
  rows/counts/rule_set/base_rule_set literal из примера, а `draft_revision`
  равна провалидированной текущей ревизии, поэтому `GET /dictionary` и
  `POST .../simulate` согласованы.
- `getSimulation` — чтение: требует только активную mock-сессию, отдаёт
  сохранённую страницу по непрозрачному курсору (`page1 → page2`) и finite
  `limit` (1..100). Неизвестный `simulation_id` → 404 `NOT_FOUND`,
  недействительный `cursor`/`limit` → 422 `VALIDATION_ERROR`. Операция
  объявляет только 200/401/403/404/422/429/500/503: 409 здесь **не**
  возвращается, и последующее изменение черновика не меняет сохранённый
  результат (staleness — предмет publish, LT-07.1c).
- `counts` не двойного счёта: `total = will_move + will_manual_review +
  requires_decision + not_ready`; `rule_conflicts`/`no_scenario` — дополнительные
  причины. `base_rule_set` полный, а не-draft references входят в его
  `members`; `version_id=null` встречается только у ссылок тестируемого
  черновика. `ready_snapshot_id` соответствует сценарию.
- `MockController` управляет объявленными ошибками симуляции:
  `setError(operation, code)` / `failNext(operation, code)` / `clearError` /
  `consumeSimulationError` для `createDictionarySimulation`/`getSimulation`.
  Коды ограничены объявленными для каждой операции (`declaredSimulationErrors`
  из `@/mocks`): для `createDictionarySimulation` — `DRAFT_VERSION_CONFLICT`,
  `VALIDATION_ERROR`; для `getSimulation` — только `VALIDATION_ERROR`.
  `STALE_SIMULATION` объявлен лишь для `publishDictionary` и в набор симуляции
  не входит; тело/статус берутся из `contracts/examples/errors/*.json`.
  `reset()` восстанавливает seed симуляций, сценарий `full` и очищает
  управляемые ошибки.

Проверки: `tests/mocks/simulations.test.ts` — literal canned-ответы
full/empty/conflict/same-target/no-scenario, counts/`base_rule_set` references,
согласованная revision-семантика (`GET /dictionary` ↔ create), paging
page1→page2 без 409, 401/403/404/422, управляемые ошибки по объявленным кодам и
`reset()`.

## Mock publishing/versions/restore (LT-07.1c)

`src/mocks/handlers/publishing.ts` подключает к mock-fetch четыре операции
WP-07 без backend, matcher, RuleSet-вычисления и файловых действий:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /dictionaries/{dictionary_id}/publish` | 201 `PublishedDictionaryResponse` | canned v2/v3, gates, `Idempotency-Key`; CSRF обязателен |
| `GET /dictionaries/{dictionary_id}/versions` | 200 `PageDictionaryVersion` | история newest-first, `cursor`/`limit` |
| `GET /dictionaries/{dictionary_id}/versions/{version_id}` | 200 `DictionaryVersion` | неизвестный → 404 `NOT_FOUND` |
| `POST /dictionaries/{dictionary_id}/restore-draft` | 200 `Dictionary` | `revision+1`, `based_on_version_id`; CSRF обязателен |

- Данные берутся из публичных примеров `contracts/examples/dictionaries/*.json`
  через `src/mocks/publishing/store.ts`: seed-версии
  (`version-atlas-general-v1`, `version-atlas-invoices-v1`,
  `version-nova-general-v1`), canned `publish-atlas-general-v2/v3` и canned
  `dictionary-atlas-general-restored-v1`. Publish append'ит literal
  `published_version` и literal `rule_set`; RuleSet не пересчитывается.
- `publishDictionary` требует сессию, корректный `X-CSRF-Token` (общий guard
  `requireSessionAndCsrf`) и непустой `Idempotency-Key`, валидирует
  `PublishDictionaryRequest` (`comment` 1–500). Gates воспроизводимы по
  canned-состоянию: неизвестный dictionary/simulation → 404;
  `expected_draft_revision` ≠ текущей ревизии `DictionaryStore` → 409
  `DRAFT_VERSION_CONFLICT`; simulation, зафиксированная на другой ревизии, или
  истёкшая (инъекция `setPublishingNow`) → 409 `STALE_SIMULATION`;
  `counts.rule_conflicts > 0` → 409 `RULE_CONFLICT`; `counts.no_scenario > 0`
  без `acknowledge_no_scenario` → 409 `NO_SCENARIO_ACK_REQUIRED`. Успех — 201
  literal `publish-atlas-general-v2`/`v3` (выбор
  `setPublishingScenario('v2' | 'v3')`), обновление `DictionaryStore`, истории
  версий и active RuleSet. Сортировка/партия не запускаются.
- Идемпотентность на mock-стороне scoped по actor+dictionary+ключу: повтор того
  же ключа/тела возвращает прежний результат **до** staleness-проверок (API §2,
  потерянный ответ), другое тело с тем же ключом → 409
  `IDEMPOTENCY_KEY_REUSED`; новый ключ — новая операция. Ключ проверяется до
  TTL/ревизии, поэтому replay принятой публикации работает и при устаревшем
  тесте.
- `restoreDictionaryDraft` валидирует `{version_id, expected_draft_revision}`,
  неизвестный dictionary/version → 404, stale-ревизия → 409
  `DRAFT_VERSION_CONFLICT`. Успех переносит name/description/rules версии в
  черновик (`revision+1`, `based_on_version_id` установлен) и помечает черновик
  восстановленным. Restore — не публикация (API §6): `active_version_id` и
  `versions_count` берутся из текущего `DictionaryStore` и **никогда** не
  меняются. Canned-пример `dictionary-atlas-general-restored-v1` применяется
  только при выполнении его предусловий (канонический сценарий restore после
  publish v2: active v2, история v1+v2, `versions_count=2`, и запрошена именно
  `version-atlas-general-v1`, которую восстанавливает canned); иначе черновик
  собирается из name/description/rules ИМЕННО запрошенной версии с
  `based_on_version_id=version_id`, поэтому для любой отданной
  `active_version_id` `GET /versions/{version_id}` отвечает 200 — «висячего»
  active нет и выбранная версия не подменяется. Последующая ручная правка (`PUT /draft`) очищает
  `based_on_version_id` (API §6), после чего черновик — обычный новый кандидат.
- `listDictionaryVersions`/`getDictionaryVersion` — чтение: только активная
  mock-сессия, неизвестный dictionary/version → 404, недействительный
  `cursor`/`limit` → 422; 409 у чтения не объявлен и не возвращается. После
  публикаций v2/v3 список равен literal `versions-atlas-general` (v3/v2/v1).
- `MockController` управляет объявленными ошибками публикации:
  `setError(operation, code)` / `failNext(operation, code)` / `clearError` /
  `consumePublishingError`. Коды ограничены объявленными для каждой операции
  (`declaredPublishingErrors` из `@/mocks`): для `publishDictionary` —
  `DRAFT_VERSION_CONFLICT`, `STALE_SIMULATION`, `RULE_CONFLICT`,
  `NO_SCENARIO_ACK_REQUIRED`, `IDEMPOTENCY_KEY_REUSED`, `VALIDATION_ERROR`; для
  `listDictionaryVersions`/`getDictionaryVersion` — только `VALIDATION_ERROR`;
  для `restoreDictionaryDraft` — `DRAFT_VERSION_CONFLICT`, `VALIDATION_ERROR`.
  Тело/статус берутся из `contracts/examples/errors/*.json`. `reset()`
  восстанавливает seed публикаций, сценарий `v2`, снимает TTL-время и очищает
  управляемые ошибки.

Проверки: `tests/mocks/publishing.test.ts` — literal publish v2/v3,
dictionary/version/RuleSet и отсутствие сортировки, gates
rule/ack/stale/TTL/comment 0–501, идемпотентный retry/reuse/lost response,
versions list/get/paging, restore/provenance (canned v1 и fallback для
запрошенной v2; неканонический save-без-publish без смены
active/`versions_count` и без «висячего» active), ручная правка,
401/403/404/422, управляемые ошибки по объявленным кодам и `reset()`.

## Mock queue/selection (LT-07.2a)

`src/mocks/handlers/sorting.ts` подключает к mock-fetch две операции WP-07 без
matcher, readiness-детектора, claim/snapshot-алгоритма и файловых действий:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /sorting/queue/query` | 200 `QueueResponse` | canned-сценарий очереди, literal counters/generation; чтение без CSRF |
| `POST /sorting/selections` | 201 `SelectionSnapshot` | EXPLICIT/ALL_MATCHING, снимок; CSRF обязателен |

- Данные берутся из публичных примеров `contracts/examples/sorting/*.json`
  через `src/mocks/sorting/queue.ts` и `src/mocks/sorting/selection.ts`:
  `queue-ready-120-page1`, `queue-ready-0`, `queue-ready-1001-page1`,
  `queue-all-active-120`, `queue-all-active-0`, `queue-missing-explicit`,
  `queue-query-text`, `selection-snapshot-explicit-one/multiple`,
  `selection-snapshot-all-matching-120`. Никакие counters/status_counts/
  matching_count/eligible_count/membership не вычисляются: это literal
  значения примеров.
- `querySortingQueue` — чтение (`csrf: false`): требует активную mock-сессию,
  валидирует `QueueQueryRequest` по схеме OAS (company_id, filters, cursor,
  limit 1..100) и отдаёт canned-ответ выбранного сценария. Сценарий выбирает
  `MockController.setQueueScenario('ready-120' | 'ready-0' | 'ready-1001' |
  'all-active-120' | 'all-active-0' | 'missing-explicit' | 'query-text')` (по
  умолчанию `ready-120`); фильтры запроса должны соответствовать сценарию,
  иначе → 422 `VALIDATION_ERROR` без правдоподобного, но неверного успеха.
  Объявлена только первая страница, поэтому непустой `cursor` → 422
  `VALIDATION_ERROR`: mock не синтезирует вторую страницу.
- `createSortingSelection` — объявленная мутация (`csrf: true`): требует
  активную mock-сессию и корректный `X-CSRF-Token` (общий guard
  `requireSessionAndCsrf`), валидирует `SelectionRequest` (oneOf
  EXPLICIT/ALL_MATCHING). EXPLICIT отдаёт canned snapshot по числу элементов
  (`selected_count` = число переданных items). ALL_MATCHING сверяет
  `expected_eligible_count` с canned `eligible_count` текущего queue-сценария:
  0 → 422 `EMPTY_SELECTION`; > 1000 → 422 `BATCH_LIMIT_EXCEEDED` без усечения;
  расхождение → 409 `SELECTION_CHANGED`; иначе — 201 literal
  `selection-snapshot-all-matching-120` с `selected_count` =
  `expected_eligible_count` и `queue_generation` сценария. Созданный снимок
  сохраняется в `SelectionStore`, поэтому поздние поступления и смена
  queue-сценария его не меняют.
- `SelectionStore.resolve(selection_id, { actorId, now })` воспроизводит
  семантику использования снимка, объявленную для preview/batch, а не для
  create: неизвестный id → `not_found` (404 `NOT_FOUND`), другой `user_id` →
  `forbidden` (403 `FORBIDDEN`), истёкший `expires_at` при заданном
  `setSelectionNow` → `expired` (409 `SELECTION_EXPIRED`). `create` эти
  необъявленные для него статусы не возвращает. Хелперы
  `selectionUseErrorResponse` и `declaredSelectionUseErrors` экспортируются из
  `@/mocks` для следующих листьев preview/batch.
- `MockController` управляет очередью/выбором: `setQueueScenario`,
  `setEligibleCountOverride` (mismatch `expected_eligible_count`),
  `setSelectionNow` (TTL снимка), `getSelectionStore`, а также объявленные
  ошибки операций через `setError(operation, code)` / `failNext(operation,
  code)` / `clearError` / `consumeSortingError`. Наборы строго разделены по
  операциям (`sortingErrorCodesByOperation`, `isSortingErrorDeclaredForOperation`
  из `@/mocks`): `querySortingQueue` — `UNAUTHENTICATED`/`FORBIDDEN`/
  `VALIDATION_ERROR`/`RATE_LIMITED`/`INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`;
  `createSortingSelection` — те же плюс `SELECTION_CHANGED`/`EMPTY_SELECTION`/
  `BATCH_LIMIT_EXCEEDED`. Overload'ы не принимают код другой операции, а
  runtime-guard игнорирует такой код, поэтому undeclared HTTP-статус
  невозможен. Тело/статус берутся из `contracts/examples/errors/*.json`; для
  `SERVICE_UNAVAILABLE` (503) контрактного файла нет, поэтому тело
  синтезируется по inline-примеру OAS `ErrorSERVICE_UNAVAILABLE`
  (`retryable:true`, `operation_id:null`, пустые `field_errors`). `reset()`
  восстанавливает сценарий `ready-120`, снимает override/TTL и очищает store и
  управляемые ошибки.

Проверки: `tests/mocks/sorting-queue-selection.test.ts` — 7 literal
queue-сценариев (0/120/1001, все активные 0/120, MISSING, query_text),
counters/generation/next_cursor, несоответствие фильтров/cursor/limit → 422,
EXPLICIT one/multiple, ALL_MATCHING 120, 0 → `EMPTY_SELECTION`, 1001 →
`BATCH_LIMIT_EXCEEDED`, count change → `SELECTION_CHANGED`, поздние поступления,
owner/expiry/unknown снимка, 503 = `SERVICE_UNAVAILABLE` (никогда
`SEARCH_UNAVAILABLE`), per-operation ограничение managed-кодов, 401/403/404/422,
управляемые ошибки и `reset()`.

## Mock preview (LT-07.2b)

`src/mocks/handlers/previews.ts` подключает к mock-fetch две операции WP-07 без
matcher, ranking, расчёта плана/целей и файловых действий:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /sorting/previews` | 201 `Preview` | canned-сценарий, первая страница; CSRF обязателен; preview ничего не перемещает |
| `GET /sorting/previews/{preview_id}` | 200 `Preview` | сохранённая страница `rows`; `cursor`/`limit`; чтение не продлевает срок |

- Данные берутся из публичных примеров `contracts/examples/sorting/preview-*.json`
  через `src/mocks/sorting/preview.ts`: `preview-atlas-explicit-one`,
  `preview-atlas-explicit-multiple`, `preview-atlas-allmatching-120-page1`,
  `preview-atlas-hetero`, `preview-atlas-conflict`. Rows/counts/targets/
  collisions/`rule_set` не пересчитываются — это literal прогноз. Matcher,
  ranking, readiness-детектор и движение файлов отсутствуют.
- `createSortingPreview` — объявленная мутация (`csrf: true`): требует сессию и
  корректный `X-CSRF-Token` (общий guard `requireSessionAndCsrf`), валидирует
  `PreviewCreateRequest` (`selection_id`; лишнее/отсутствующее поле, битый JSON →
  422 `VALIDATION_ERROR`). Снимок разрешается через
  `SelectionStore.resolve(selection_id, { actorId, now })` строго объявленными
  кодами: неизвестный id → 404 `NOT_FOUND`, другой `user_id` → 403 `FORBIDDEN`,
  истёкший `expires_at` (инъекция `setSelectionNow`) → 409 `SELECTION_EXPIRED`.
- Сценарий выбирает `MockController.setPreviewScenario('explicit-one' |
  'explicit-multiple' | 'allmatching-120' | 'hetero' | 'conflict' | null)`. При
  `null` сценарий выводится из разрешённого снимка: ALL_MATCHING →
  `allmatching-120`; EXPLICIT с одним элементом → `explicit-one`, с несколькими →
  `explicit-multiple`. `hetero` и `conflict` выбираются явно: первый покрывает
  все `Prediction` (`WILL_MOVE`/`WILL_MANUAL_REVIEW`/`REQUIRES_DECISION`/
  `NOT_READY`) и все `CollisionDetails.kind` (`EXISTING_TARGET`/
  `DUPLICATE_PLAN_TARGET`/`MANUAL_REVIEW_NAME`) с nullable `target`/
  `existing_target_metadata`; второй — `RULE_CONFLICT` с `selected_rule=null`.
  `selection_id`/`company_id` ответа привязываются к разрешённому снимку.
- Объявлена только первая страница (у `allmatching-120` непустой `next_cursor`);
  второй страницы в примерах нет, поэтому `GET` с непустым `cursor` → 422
  `VALIDATION_ERROR`, а mock не синтезирует страницу. `limit` валидируется
  (1..100), неизвестный `preview_id` → 404 `NOT_FOUND`. `GET` не объявляет 409:
  чтение отдаёт сохранённый `expires_at` без продления (`PreviewStore.isExpired`
  доступен batch-листу LT-07.2c, где `STALE_PREVIEW` объявлен для
  `createSortingBatch`). Preview не создаёт batch и не выполняет movement.
- `MockController` управляет preview: `setPreviewScenario`/`getPreviewScenario`,
  `setPreviewNow`/`getPreviewNow`, `getPreviewStore`, а также объявленные ошибки
  операций через `setError(operation, code)` / `failNext(operation, code)` /
  `clearError` / `consumePreviewError`. Наборы строго разделены по операциям
  (`sortingErrorCodesByOperation`): `createSortingPreview` —
  `UNAUTHENTICATED`/`FORBIDDEN`/`NOT_FOUND`/`SELECTION_EXPIRED`/
  `SELECTION_CHANGED`/`INVALID_STATE`/`VALIDATION_ERROR`/`RATE_LIMITED`/
  `INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`; `getSortingPreview` — те же без 409
  (`SELECTION_EXPIRED`/`SELECTION_CHANGED`/`INVALID_STATE`). `STALE_PREVIEW`
  объявлен только для `createSortingBatch` (LT-07.2c) и через
  `declaredSelectionUseErrors`/`selectionUseErrorResponse` доступен
  инфраструктуре, но preview-операции его не возвращают. Overload'ы и
  runtime-guard не допускают undeclared HTTP-статус. Тело/статус берутся из
  `contracts/examples/errors/*.json`; `SERVICE_UNAVAILABLE` синтезируется по
  inline-примеру OAS. `reset()` снимает сценарий/`now` и очищает store и ошибки.

Проверки: `tests/mocks/sorting-preview.test.ts` — маршрутизация двух операций,
literal EXPLICIT one/multiple и ALL_MATCHING page1 (100 rows, непустой cursor),
hetero (все Prediction/CollisionDetails kinds, nullable target/metadata),
conflict (`RULE_CONFLICT`), вывод сценария из снимка, отсутствие batch/movement,
owner/expiry/unknown снимка (403/409/404), `get` page1/cursor/limit/unknown,
непродление TTL, 401/403/422, управляемые ошибки по объявленным кодам,
per-operation ограничение и `reset()`.

## Mock batches (LT-07.2c)

`src/mocks/handlers/batches.ts` подключает к mock-fetch три операции WP-07 без
claim, executor, matcher, перемещения файлов и подсчёта progress:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /sorting/batches` | 202 `Batch` | DIRECT/PREVIEWED, gates, `Idempotency-Key`; CSRF обязателен; 202 ≠ завершение |
| `GET /sorting/batches/{batch_id}` | 200 `Batch` | текущий прогресс и страница outcomes; `cursor`/`limit` |
| `GET /sorting/batches` | 200 `BatchPage` | `BatchSummary` компании, `created_at DESC`/`batch_id DESC`; `cursor`/`limit` |

- Данные берутся из публичных примеров
  `contracts/examples/sorting/batch-*.json` через `src/mocks/sorting/batch.ts`:
  `batch-atlas-direct-fresh-page1/page2`,
  `batch-atlas-previewed-fresh-page1/page2`, `batch-atlas-sorted`,
  `batch-atlas-conflict`, `batch-atlas-hetero`, `batch-atlas-technical`,
  `batch-atlas-same-user-session` и история `batch-history-atlas-page1`.
  Статусы, counts, outcomes, причины и timestamps не пересчитываются — это
  literal данные примера. Matcher, claim, executor и recovery отсутствуют.
- Сценарий выбирает `MockController.setBatchScenario('direct-fresh' |
  'previewed-fresh' | 'sorted' | 'conflict' | 'hetero' | 'technical' |
  'same-user-session' | null)`. При `null` `createSortingBatch` выводит его из
  `execution_mode` (DIRECT → `direct-fresh`, PREVIEWED → `previewed-fresh`).
  `setBatchPhase('ACCEPTED' | 'RUNNING' | 'COMPLETED' | 'COMPLETED_WITH_ISSUES' |
  'RECOVERY_REQUIRED')` переключает фазу прогресса: `getSortingBatch` отдаёт
  соответствующую canned-страницу (`PHASE_SCENARIO`) без реальных таймеров.
  `seedBatchHistory()` заполняет store literal-историей для list/get.
- `createSortingBatch` требует сессию, корректный `X-CSRF-Token` (общий guard
  `requireSessionAndCsrf`) и непустой `Idempotency-Key`, валидирует
  `BatchCreateRequest` (oneOf DIRECT/PREVIEWED; PREVIEWED требует
  `preview_id`, DIRECT — нет). Gates воспроизводимы объявленными кодами:
  неизвестный selection/preview → 404 `NOT_FOUND`; другой owner → 403
  `FORBIDDEN`; истёкший selection (инъекция `setSelectionNow`) → 409
  `SELECTION_EXPIRED`; preview другой пары/компании → 409 `INVALID_STATE`;
  DIRECT с изменённым источником (`setBatchGate('SELECTION_CHANGED')`) → 409
  `SELECTION_CHANGED`; PREVIEWED с устаревшим preview (gate или
  `setPreviewNow`) → 409 `STALE_PREVIEW`; превышение предела
  (`setBatchGate('BATCH_LIMIT_EXCEEDED')`) → 422 `VALIDATION_ERROR`. Успех —
  202 literal `Batch` (page1 сценария). 202 означает принятие, а не завершение.
- Идемпотентность scoped по actor+ключу: повтор того же ключа/тела возвращает
  прежнюю партию **до** staleness-проверок (API §2, потерянный ответ), другое
  тело с тем же ключом → 409 `IDEMPOTENCY_KEY_REUSED`; новый ключ создаёт
  новую партию с уникальным `batch_id`; тот же ключ у другого пользователя —
  своя партия. `bindBatchPage` привязывает identity принятой партии
  (`batch_id`/`company_id`/`selection_id`/`preview_id`/`actor`/`rule_set`/
  `created_at`) к canned-странице фазы, поэтому GET по созданному id
  самосогласован.
- `getSortingBatch` — чтение: только активная mock-сессия, literal-страница
  текущей фазы (page1/page2 через непрозрачный `cursor`), неизвестный
  `batch_id` → 404 `NOT_FOUND`, невалидный `cursor`/`limit` → 422. 409 у
  чтения не объявлен. Партия `RECOVERY_REQUIRED` остаётся незавершённой
  (`finished_at=null`, `recovery_required>0`).
- `listSortingBatches` — чтение: `company_id` обязателен, `BatchSummary`
  компании в порядке `created_at DESC`, `batch_id DESC`; `cursor` — конечный
  `batches-offset-<n>`, `limit` 1..100; невалидные → 422. Другая компания даёт
  пустую страницу. Созданные партии появляются в списке.
- `MockController` управляет партиями: `setBatchScenario`/`getBatchScenario`,
  `setBatchPhase`/`getBatchPhase`, `setBatchGate`/`getBatchGate`,
  `getBatchStore`, `seedBatchHistory`, а также объявленные ошибки операций
  через `setError(operation, code)` / `failNext(operation, code)` /
  `clearError` / `consumeBatchError`. Наборы строго разделены по операциям
  (`batchErrorCodesByOperation`, `isBatchErrorDeclaredForOperation` из
  `@/mocks`): `createSortingBatch` — `UNAUTHENTICATED`/`FORBIDDEN`/
  `CSRF_FAILED`/`NOT_FOUND`/`IDEMPOTENCY_KEY_REUSED`/`INVALID_STATE`/
  `SELECTION_EXPIRED`/`SELECTION_CHANGED`/`STALE_PREVIEW`/`VALIDATION_ERROR`/
  `RATE_LIMITED`/`INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`; `getSortingBatch` — те
  же без 409; `listSortingBatches` — без 404/409. `BATCH_LIMIT_EXCEEDED`
  объявлен только для `createSortingSelection` и в набор партий не входит;
  422 партии использует только `VALIDATION_ERROR` (OAS `ValidationError`).
  Тело/статус берутся из `contracts/examples/errors/*.json`;
  `SERVICE_UNAVAILABLE` синтезируется по inline-примеру OAS. `reset()`
  очищает сценарий/фазу/gate, store, ошибки и созданные снимки/preview.
- Movement не выполняется: создание партии не запускает executor, не меняет
  снимок выбора и не делает файловых операций. Mock-прохождение не является
  доказательством файловой безопасности или реальной concurrency.

Проверки: `tests/mocks/sorting-batch.test.ts` — маршрутизация трёх операций,
literal submit DIRECT/PREVIEWED, lost response/replay (в т.ч. при устаревшем
selection), reuse/новый key/user-scope, gates 404/403/409
`INVALID_STATE`/`SELECTION_EXPIRED`/`SELECTION_CHANGED`/`STALE_PREVIEW`/422
`VALIDATION_ERROR`, paging page1/page2, прогресс по фазам, все
`BatchState`/`OutcomeState`/reason_code, recovery (`finished_at=null`),
согласованность counts, company-scoped list и порядок/cursor, 401/403/422,
управляемые ошибки по объявленным кодам, per-operation ограничение и `reset()`.

## Mock quarantine/return (LT-07.3a)

`src/mocks/handlers/quarantine.ts` подключает к mock-fetch две операции WP-07
без реального возврата, recovery, перемещения файлов, автосортировки и журнала:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `GET /quarantine` | 200 `QuarantinePage` | literal подтверждённых записей компании; `cursor`/`limit`; чтение без CSRF |
| `POST /quarantine/{quarantine_id}/return` | 200 `QuarantineReturnResponse` | `expected_revision`/`comment`, gates, `Idempotency-Key`; CSRF обязателен |

- Данные берутся из публичных примеров `contracts/examples/quarantine/*.json`
  через `src/mocks/quarantine/store.ts`:
  `quarantine-item-atlas-technical`, `quarantine-item-atlas-ambiguous`,
  `quarantine-list-atlas`, `quarantine-return-response`. Возврат, recovery,
  matcher, перемещение и автосортировка не выполняются: store лишь хранит
  literal-записи и отдаёт объявленные состояния/конфликты.
- Состояние записи выбирает `MockController.setQuarantineScenario('technical' |
  'ambiguous' | 'returned')` (по умолчанию `technical`):
  `technical` — возвратимая запись (`can_return=true`, revision=1);
  `ambiguous` — `can_return=false` с зарегистрированным
  `recovery_operation_id` (revision=3);
  `returned` — уже возвращённая запись (повтор с новым ключом → 409
  `INVALID_STATE`). `setQuarantineCanReturn(true|false)` — sugar над выбором
  состояния, `getQuarantineCanReturn()` возвращает текущий флаг стабильности.
  `setQuarantineGate('ORIGINAL_PATH_OCCUPIED')` воспроизводит занятый исходный
  путь. `can_return` — серверный флаг стабильности из OAS, не право/роль:
  `false` всегда сопровождается зарегистрированной recovery-операцией.
- `listQuarantineItems` — чтение (`csrf: false`): требует активную
  mock-сессию, `company_id` обязателен, `limit` 1..100, `cursor` — конечный
  `quarantine-offset-<n>`. Список company-scoped и содержит только
  подтверждённые записи карантина (RECOVERY_REQUIRED-исходы партии не входят);
  неизвестная компания даёт пустую страницу. Невалидный `cursor`/`limit` и
  отсутствие `company_id` → 422 `VALIDATION_ERROR`.
- `returnQuarantineItem` — объявленная мутация (`csrf: true`,
  `idempotencyKey: true`): требует сессию, корректный `X-CSRF-Token` (общий
  guard `requireSessionAndCsrf`) и непустой `Idempotency-Key`, валидирует
  `QuarantineReturnRequest` (`expected_revision`, `comment` 1..500). Gates
  воспроизводимы объявленными кодами: неизвестный `quarantine_id` → 404
  `NOT_FOUND`; уже возвращённая запись → 409 `INVALID_STATE`; неоднозначный
  возврат → 409 `RECOVERY_REQUIRED` с `error.operation_id` = зарегистрированной
  операции; устаревшая `expected_revision` → 409
  `QUARANTINE_VERSION_CONFLICT`; занятый исходный путь → 409
  `ORIGINAL_PATH_OCCUPIED` без мутаций; comment вне 1..500 → 422
  `VALIDATION_ERROR` (`error-quarantine-comment-validation`). Успех — 200
  literal `QuarantineReturnResponse` (`item.status=WAITING_READY`,
  `selectable=false`, без `active_attempt_id`), без batch POST и автосортировки.
- Идемпотентность scoped по actor+ключу: повтор того же ключа/тела возвращает
  прежний исход (успех или зарегистрированный recovery) **до**
  staleness/state-проверок (API §2, потерянный ответ); другое тело с тем же
  ключом → 409 `IDEMPOTENCY_KEY_REUSED`; тот же ключ у другого пользователя —
  отдельный scope, а не глобальный конфликт. После успешного возврата запись
  помечается возвращённой, поэтому `GET /quarantine` отражает обновлённое
  (пустое) состояние, а новый ключ даёт 409 `INVALID_STATE`.
- `MockController` управляет карантином: `setQuarantineScenario`/
  `getQuarantineScenario`, `setQuarantineCanReturn`/`getQuarantineCanReturn`,
  `setQuarantineGate`/`getQuarantineGate`, `getQuarantineStore`, а также
  объявленные ошибки операций через `setError(operation, code)` /
  `failNext(operation, code)` / `clearError` / `consumeQuarantineError`. Наборы
  строго разделены по операциям (`quarantineErrorCodesByOperation`,
  `isQuarantineErrorDeclaredForOperation` из `@/mocks`): `listQuarantineItems` —
  `UNAUTHENTICATED`/`FORBIDDEN`/`VALIDATION_ERROR`/`RATE_LIMITED`/
  `INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`; `returnQuarantineItem` — те же плюс
  `CSRF_FAILED`/`NOT_FOUND`/`IDEMPOTENCY_KEY_REUSED`/
  `QUARANTINE_VERSION_CONFLICT`/`ORIGINAL_PATH_OCCUPIED`/`INVALID_STATE`/
  `RECOVERY_REQUIRED`. Overload'ы и runtime-guard не допускают undeclared
  HTTP-статус. Тело/статус берутся из `contracts/examples/errors/*.json`;
  `SERVICE_UNAVAILABLE` синтезируется по inline-примеру OAS. Recovery endpoint
  не добавляется. `reset()` возвращает сценарий `technical`, снимает gate,
  очищает store и управляемые ошибки.
- Файловых операций нет: mock не выполняет возврат и не является
  доказательством файловой безопасности. Mock-прохождение не является
  real-backend evidence.

Проверки: `tests/mocks/quarantine.test.ts` — маршрутизация двух операций,
literal подтверждённый список/company-scope/paging/cursor, can_return/recovery,
успешный возврат WAITING_READY без batch/автосортировки, границы comment
0/1/500/501, конфликты 404/409 (`INVALID_STATE`/`QUARANTINE_VERSION_CONFLICT`/
`ORIGINAL_PATH_OCCUPIED`/`RECOVERY_REQUIRED` с `operation_id`/
`IDEMPOTENCY_KEY_REUSED`), идемпотентный replay success/recovery и user-scope,
новый ключ, 401/403/404/422, управляемые ошибки по объявленным кодам,
per-operation ограничение, позднее состояние списка и `reset()`.

## Mock audit journal (LT-07.3b)

`src/mocks/handlers/audit.ts` подключает к mock-fetch три операции чтения
WP-07 без записи, immutability, серверного фильтр-алгоритма, cursor-store и
actor-directory:

| Метод и путь | Ответ | Особенности |
|---|---|---|
| `POST /audit/query` | 200 `AuditQueryResponse` | literal canned-страница; `AuditQueryRequest` в теле; интервал `[from,to)`; роли WORKER/ADMIN |
| `GET /audit/updates` | 200 `AuditUpdatesResponse` | `after_event_id?`; `{has_new_events}` без текстов фильтров |
| `GET /audit/actors` | 200 `ActorPage` | literal авторы, включая заблокированного; `prefix`/`cursor`/`limit` |

- Данные берутся из публичных примеров `contracts/examples/audit/*.json`
  через `src/mocks/audit/store.ts`: `audit-query-day-atlas`,
  `audit-query-batch-accepted`, `audit-query-issue`,
  `audit-query-cursor-page2`, `audit-query-empty-window`,
  `audit-actors-atlas`, `audit-updates-after-known`. Запись, immutability,
  matcher/ranking, cursor-store и actor-directory не выполняются: store лишь
  хранит literal canned-страницы и делает lookup по фильтрам/сценарию.
- `queryAuditEvents` — чтение (`csrf: false`): требует активную mock-сессию,
  валидирует `AuditQueryRequest` (nullable `company_id`/`actor_id`/`action`/
  `result`, `query_text`, `cursor`, `limit` 1..100) и объявленный порядок
  интервала `[from,to)`. Невалидный интервал (`from >= to`) → 422
  `VALIDATION_ERROR` с примером `error-audit-validation` (поле `from`,
  код `ORDER`); невалидная схема/`limit` → 422. Чувствительные фильтры идут в
  теле POST и не попадают в URL; они не журналируются и не сохраняются.
- Выбор canned-страницы: `action=BATCH_ACCEPTED` → batch-accepted,
  `result=ISSUE` → issue, известный курсор второй страницы
  (`cursor-audit-atlas-page2`/`cursor-audit-primary-page2`) → cursor-page2,
  окно после canned-дня → empty, компания кроме Atlas → пустая страница,
  иначе — day. `MockController.setAuditScenario('day'|'issue'|'batch-accepted'|
  'cursor-page2'|'empty')` задаёт сценарий напрямую; `getAuditScenario()` его
  читает. `actor_id`/`query_text` отбирают literal-элементы уже выбранной
  страницы (регистронезависимо по имени/логическому пути), не вычисляя
  серверный matcher.
- Роль из сессии: WORKER видит только BUSINESS, ADMIN — BUSINESS+SYSTEM
  (canned-переключение). SYSTEM-события (включая единственный допустимый
  `actor=null` у `LOGIN_FAILED` без инициатора) взяты literal из канонического
  эталона `fixtures/synthetic/audit_expectations.json`; для BUSINESS
  `actor=null` не выдумывается. Связи `request_id`/`operation_id`/
  `source_attempt_id`/`batch_id`/`version_id`/`dictionary_id`/`item_id`
  остаются literal из примеров.
- `getAuditUpdates` — чтение: `after_event_id` необязателен; отсутствие
  параметра означает первичный пустой журнал без нижней границы. Непустой
  журнал без параметра сообщает `true`, пустой (`setAuditJournalEmpty(true)`) —
  `false`; после новейшего доступного события роли — `false`, иначе `true`.
  Пустой `after_event_id` → 422; тексты фильтров в URL не передаются.
- `listAuditActors` — чтение: `prefix` регистронезависим по login/
  display_name, `limit` 1..100, `cursor` — конечный `audit-actors-offset-<n>`.
  Literal `audit-actors-atlas` включает заблокированного автора с доступными
  событиями; несовпавший prefix и неизвестный курсор дают пустую страницу и
  422 соответственно.
- `MockController` управляет журналом: `getAuditStore`, `setAuditScenario`/
  `getAuditScenario`, `setAuditJournalEmpty`/`isAuditJournalEmpty`, а также
  объявленные ошибки через `setError(operation, code)` /
  `failNext(operation, code)` / `clearError` / `consumeAuditError`. Набор
  (`auditErrorCodesByOperation`, `isAuditErrorDeclaredForOperation` из
  `@/mocks`) одинаков для трёх операций: `UNAUTHENTICATED`/`FORBIDDEN`/
  `VALIDATION_ERROR`/`RATE_LIMITED`/`INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`;
  `CSRF_FAILED` и 404/409 журналу не объявлены. Overload'ы и runtime-guard не
  допускают undeclared HTTP-статус. `reset()` снимает сценарий, флаг пустого
  журнала и управляемые ошибки.
- Mock не является доказательством реального аудита, immutability или
  файловой безопасности. Mock-прохождение не является real-backend evidence.

Проверки: `tests/mocks/audit.test.ts` — маршрутизация трёх операций,
literal day/issue/batch-accepted/cursor-page2/empty с порядком и
`newest_event_id`, фильтры company/from-to/actor/action/result/query_text,
невалидный интервал 422, роль WORKER/ADMIN и null-actor только SYSTEM,
обновления true/false/пустой журнал, авторы/prefix/cursor/заблокированный
автор, literal связи request/operation/source-attempt/batch/version/
dictionary, 401/403/422, управляемые ошибки по объявленным кодам,
per-operation ограничение и `reset()`.

## Структура

```text
frontend/
  index.html
  scripts/
    generate-api.mjs          генерация schema.ts + openapi.json + operation-meta.ts
    check-generated.mjs       проверка повторной генерации без diff
  src/
    main.tsx            точка входа React
    App.tsx             композиция: AppConfigProvider + AppShell
    app/
      AppShell.tsx      русская оболочка и навигация по разделам
      sections.ts       состав/порядок разделов
      shell.css         стили оболочки, состояний config и фокуса
      private-state-registry.ts  общий реестр сброса приватного состояния
      session-state.ts  in-memory контейнер присутствия сессии (LT-08.2)
      app-api.ts        единая фабрика API-клиента real/mock (LT-08.2)
      app-config-store.ts  загрузка GET /app-config без выдуманных значений
      app-config-context.tsx  AppConfigProvider и useAppConfig
    shared/
      format.ts         дата-время/размер/количество (FE §4, Q-042)
    features/{auth,search,dictionaries,sorting,quarantine,audit}/
    api/
      generated/        generated-артефакты (schema.ts, openapi.json,
                        operation-meta.ts) и client.ts
      session-context.ts  in-memory CSRF/401-состояние и session-scope очистка
      idempotency.ts      in-memory Idempotency-Key для publish/batch/return
      retry.ts            retry/backoff policy и single-flight poll registry
      transport-error.ts  TransportError и безопасный разбор ошибок
      transport.ts        createApiClient: credentials/no-store/CSRF/idempotency/retry
    mocks/              schema-valid mocks bootstrap/session/config, поиска
                        (WP-06), targets/dictionaries, симуляции, публикации,
                        очереди/выбора, preview, партий, карантина и журнала
                        аудита (WP-07)
      index.ts          createMockFetch, MockController, MOCK_MODE
      router.ts         разбор Request, статические и `{param}` маршруты
      validate.ts       ajv-валидация запросов по generated openapi.json
      data.ts           загрузка contracts/examples через @examples + manifest
      guards.ts         общий session+CSRF guard mutation-операций
      controller.ts     delay/profile/freshness/empty/session + search
                        scope-delay/error/queue + dictionary store/errors +
                        simulation scenario/store/errors + publishing
                        scenario/store/errors + sorting queue scenario/
                        selection store/errors + preview scenario/store/
                        errors + batch scenario/phase/gate/store/errors +
                        quarantine scenario/gate/store/errors + audit
                        scenario/empty/store/errors/reset
      responses.ts      контрактные заголовки и ErrorResponse
      handlers/         health, login, getSession, logout, appConfig, roots,
                        companies, search (searchFiles/getSearchFacet),
                        targets/dictionaries (LT-07.1a),
                        simulations (LT-07.1b),
                        publishing (publish/versions/restore, LT-07.1c),
                        sorting (queue/selection, LT-07.2a),
                        previews (preview create/get, LT-07.2b),
                        batches (batch create/get/list, LT-07.2c),
                        quarantine (list/return, LT-07.3a),
                        audit (query/updates/actors, LT-07.3b)
      search/           golden search/facet foundation (LT-06.2a-i)
        corpus.ts       materializer corpus.json → SearchItem/Marker
        expectations.ts literal-resolver search_expectations.json
        errors.ts       объявленные контрактом ошибки поиска (LT-06.2b)
      dictionaries/     targets/dictionaries foundation (LT-07.1a)
        targets.ts      allowlist целей из rule_expectations.json + resolver
        store.ts        in-memory seed/store справочников, trim+casefold
        errors.ts       объявленные ошибки targets/dictionaries
      simulations/      simulation foundation (LT-07.1b)
        store.ts        literal seed/store сценариев и страниц симуляции
        errors.ts       объявленные ошибки симуляции
      publishing/       publishing/versions/restore foundation (LT-07.1c)
        store.ts        seed версий, canned publish/restore, идемпотентность
        errors.ts       объявленные ошибки публикации/версий/restore
      sorting/          queue/selection/preview/batch foundation (LT-07.2a/07.2b/07.2c)
        queue.ts        canned queue-сценарии и фильтры
        selection.ts    SelectionStore, creation/resolution снимков
        preview.ts      canned preview-сценарии, PreviewStore, paging
        batch.ts        canned batch-сценарии/фазы, BatchStore, paging
        errors.ts       объявленные ошибки очереди/выбора/preview и
                        использования снимка
        batch-errors.ts объявленные ошибки партий (LT-07.2c)
      quarantine/       карантин/возврат foundation (LT-07.3a)
        store.ts        literal записи/состояния карантина, QuarantineStore,
                        идемпотентные операции, paging
        errors.ts       объявленные ошибки list/return
      audit/            журнал аудита foundation (LT-07.3b)
        store.ts        literal canned-страницы/сценарии, SYSTEM-события,
                        AuditStore, updates/actors lookup
        errors.ts       объявленные ошибки query/updates/actors
  tests/
    App.test.tsx        component smoke-тест и отсутствие запроса конфигурации
    app/app-shell.test.tsx  состав/навигация оболочки LT-08.1
    app/private-state-registry.test.ts  реестр сброса LT-08.1
    app/session-state.test.ts  контейнер присутствия сессии LT-08.2
    app/app-api.test.ts  переключатель real/mock LT-08.2
    app/app-config.test.tsx  загрузка app-config, ошибка/повтор, сброс
    shared/format.test.ts  форматы даты/размера/количества
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
    mocks/dictionaries-draft.test.ts  targets/dictionaries lifecycle mocks
    mocks/simulations.test.ts  simulation create/get, paging/stale/counts mocks
    mocks/publishing.test.ts  publish/versions/restore, gates/idempotency mocks
    mocks/sorting-queue-selection.test.ts  queue/selection canned, owner/expiry mocks
    mocks/sorting-preview.test.ts  preview create/get, predictions/collisions/expiry mocks
    mocks/sorting-batch.test.ts  batch create/get/list, progress/outcomes/gates mocks
    mocks/quarantine.test.ts  quarantine list/return, can_return/recovery/conflicts mocks
    mocks/audit.test.ts  audit query/updates/actors, roles/null-actor/links mocks
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

Browser smoke-тест (`tests/browser/smoke.spec.ts`) проверяет:

- отображение русской оболочки (`WiseWay`, навигация «Разделы приложения»,
  стартовый раздел «Поиск»);
- переключение разделов мышью и клавиатурой (`Tab` + `Enter`/`Space`);
- отсутствие запроса `GET /app-config`, пока пользователь анонимен (запрос
  перехватывается через `page.route`).

Проверки app-level клиента, контейнера сессии, провайдера `app-config` и
форматов — `npm run test` (файлы `tests/app/*` и `tests/shared/format.test.ts`).

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
