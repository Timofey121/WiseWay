// Единый безопасный HTTP-транспорт WiseWay.
//
// Транспорт строится поверх `openapi-fetch` (`createClient<paths>`) и добавляет
// общий для real/mock-режимов слой безопасности:
//
// - cookie-сессия: в real-режиме запросы идут с `credentials: 'include'`,
//   поэтому HttpOnly cookie `wiseway_session` обслуживает браузер;
// - `cache: 'no-store'` на каждом запросе — пользовательские ответы не
//   кэшируются;
// - `X-CSRF-Token` добавляется только операциям, которые объявляют
//   `#/components/parameters/XCSRFToken` в OAS, и только если токен реально
//   доступен (провайдер или in-memory session-context). На читающих запросах
//   (включая читающие POST `search`/`facet`/`queue/query`/`audit/query`) CSRF
//   не ставится;
// - `Idempotency-Key` добавляется только операциям с
//   `#/components/parameters/IdempotencyKey` (`publishDictionary`,
//   `createSortingBatch`, `returnQuarantineItem`). Ключ выдаёт in-memory
//   `idempotencyStore` и связывает его с телом запроса: повтор того же тела
//   сохраняет ключ, изменённое тело получает новый. Успех/окончательный
//   не-retryable отказ освобождают действие (`complete`), сетевой/429/503
//   исход сохраняет его (`retain`). Остальные операции фиктивного ключа не
//   получают;
// - CSRF и ключ идут только в заголовках, не в теле запроса;
// - `X-Request-ID` ответа передаётся в `onRequestId`;
// - ответ 401 очищает клиентскую сессию и уведомляет подписчиков
//   `session-context` только для `UNAUTHENTICATED`; `LOGIN_FAILED` остаётся
//   ошибкой формы входа без очистки; 403 не порождает автоматический повтор.
//
// Единая безопасная модель ошибок — `./transport-error` (`TransportError`,
// `toTransportError`, `isTransportError`, `throwIfError`); она реэкспортируется
// из этого модуля, чтобы потребители клиента получали безопасные
// `request_id`/`operation_id`/`field_errors` без утечки тел и секретов.
//
// Транспорт не логирует тела, секреты и поисковый текст.

import createClient, { type Client, type Middleware } from 'openapi-fetch'

import { operationMeta, type OperationMeta } from './generated/operation-meta'
import type { paths } from './generated/schema'
import {
  defaultIdempotencyStore,
  type IdempotencyStore,
} from './idempotency'
import { emitUnauthorized, getCsrfToken } from './session-context'
import { toTransportError } from './transport-error'

export {
  TransportError,
  toTransportError,
  isTransportError,
  throwIfError,
} from './transport-error'
export type {
  ApiResultLike,
  ErrorCode,
  FieldError,
  TransportErrorKind,
} from './transport-error'

/** Режим транспорта: настоящий сервер или mock-fetch. */
export type ApiMode = 'real' | 'mock'

/** Минимальный контекст операции, передаваемый провайдерам заголовков. */
export interface ApiOperationContext {
  /** operationId операции из публичного OAS. */
  operationId: string
  /** Путь-шаблон OAS, например `/dictionaries/{dictionary_id}/publish`. */
  schemaPath: string
  /** HTTP-метод в верхнем регистре. */
  method: string
}

/** Провайдер CSRF-токена; `null`/`undefined`/пустая строка означают отсутствие. */
export type CsrfTokenProvider = (
  context: ApiOperationContext,
) => string | null | undefined

/** Провайдер Idempotency-Key; отсутствие ключа означает отсутствие заголовка. */
export type IdempotencyKeyProvider = (
  context: ApiOperationContext,
) => string | null | undefined

/** Получатель `X-Request-ID` ответа. */
export type RequestIdHandler = (requestId: string) => void

export interface CreateApiClientOptions {
  /** Режим подключения. Меняет только transport config, не схемы. */
  mode: ApiMode
  /** Корень API. По умолчанию `/api/v1` из `servers` публичного OAS. */
  baseUrl?: string
  /**
   * Реализация `fetch`. В real-режиме — глобальный/пользовательский fetch,
   * в mock-режиме — обязательный перехватчик (WP-06/WP-07).
   */
  fetch?: (input: Request) => Promise<Response>
  /** Провайдер CSRF-токена; при отсутствии используется `session-context`. */
  csrfTokenProvider?: CsrfTokenProvider
  /**
   * In-memory хранилище идемпотентности. При наличии управляет ключом и его
   * жизненным циклом; при отсутствии используется session-scoped
   * `defaultIdempotencyStore` (если не задан `idempotencyKeyProvider`).
   */
  idempotencyStore?: IdempotencyStore
  /**
   * Провайдер Idempotency-Key для объявленных идемпотентных операций. Более
   * низкий приоритет, чем `idempotencyStore`, и не управляет жизненным циклом
   * ключа; оставлен для явного переопределения/тестов.
   */
  idempotencyKeyProvider?: IdempotencyKeyProvider
  /** Получатель безопасного `X-Request-ID` ответа. */
  onRequestId?: RequestIdHandler
}

/** Типизированный клиент всех операций WiseWay API. */
export type WiseWayApiClient = Client<paths>

const operationMetaByKey = operationMeta as Record<string, OperationMeta>

/** Находит metadata операции по `METHOD` и пути-шаблону OAS. */
export function findOperationMeta(
  method: string,
  schemaPath: string,
): OperationMeta | undefined {
  return operationMetaByKey[`${method.toUpperCase()} ${schemaPath}`]
}

/**
 * Стабильный action-scope операции из path-параметров (например
 * `dictionary_id`/`quarantine_id`). Позволяет держать независимые ожидающие
 * ключи для разных ресурсов одной операции.
 */
function actionScope(params: { path?: Record<string, unknown> }): string {
  const path = params.path
  if (!path) {
    return ''
  }
  return Object.keys(path)
    .sort()
    .map((name) => `${name}=${String(path[name])}`)
    .join('&')
}

/**
 * Читает тело ответа через `Response.clone()`, не расходуя оригинал, который
 * далее читает `openapi-fetch`. Возвращает `undefined`, если тела нет или оно
 * не JSON.
 */
async function readResponseBody(response: Response): Promise<unknown> {
  try {
    return await response.clone().json()
  } catch {
    return undefined
  }
}

/** Извлекает `error.code` из разобранного тела ответа. */
function extractErrorCode(body: unknown): string | null {
  if (!body || typeof body !== 'object') {
    return null
  }
  const error = (body as { error?: unknown }).error
  if (!error || typeof error !== 'object') {
    return null
  }
  const code = (error as { code?: unknown }).code
  return typeof code === 'string' ? code : null
}

/**
 * Создаёт безопасный типизированный клиент WiseWay API.
 *
 * @example
 * const api = createApiClient({ mode: 'real' })
 * const { data } = await api.GET('/session')
 */
export function createApiClient(options: CreateApiClientOptions): WiseWayApiClient {
  const { mode } = options
  const baseUrl = options.baseUrl ?? '/api/v1'
  const fetchImpl = options.fetch ?? globalThis.fetch

  if (mode === 'mock' && !options.fetch) {
    throw new Error('mock-режим требует переданный fetch-перехватчик')
  }
  if (!fetchImpl) {
    throw new Error('fetch недоступен: передайте реализацию fetch')
  }

  // Приоритет: явный store → явный provider → session-scoped store. Явный
  // provider не управляет жизненным циклом ключа и потому не смешивается с
  // автоматическим store.
  const idempotencyStore: IdempotencyStore | undefined =
    options.idempotencyStore ??
    (options.idempotencyKeyProvider ? undefined : defaultIdempotencyStore)

  const client = createClient<paths>({ baseUrl, fetch: fetchImpl })

  const securityMiddleware: Middleware = {
    async onRequest({ request, schemaPath, params }) {
      const method = request.method.toUpperCase()
      const meta = findOperationMeta(method, schemaPath)
      const headers = new Headers(request.headers)

      if (meta) {
        const context: ApiOperationContext = {
          operationId: meta.operationId,
          schemaPath,
          method,
        }
        const csrfToken = meta.csrf
          ? (options.csrfTokenProvider?.(context) || getCsrfToken())
          : null
        if (csrfToken) {
          headers.set('X-CSRF-Token', csrfToken)
        } else {
          // Транспорт — единственный источник mutation-заголовков: чтение и
          // операции без CSRF не должны нести устаревший токен.
          headers.delete('X-CSRF-Token')
        }

        let idempotencyKey: string | null | undefined = null
        if (meta.idempotencyKey) {
          if (idempotencyStore) {
            // Ключ связывается ровно с телом отправляемого запроса: то же
            // тело → тот же ключ, изменённое тело → новый ключ.
            const body = await request.clone().text()
            idempotencyKey = idempotencyStore.begin(
              meta.operationId,
              body,
              actionScope(params),
            )
          } else {
            idempotencyKey = options.idempotencyKeyProvider?.(context)
          }
        }
        if (idempotencyKey) {
          headers.set('Idempotency-Key', idempotencyKey)
        } else {
          headers.delete('Idempotency-Key')
        }
      }

      const init: RequestInit = { headers, cache: 'no-store' }
      if (mode === 'real') {
        init.credentials = 'include'
      }
      return new Request(request, init)
    },
    async onResponse({ request, response, schemaPath, params }) {
      const requestId = response.headers.get('X-Request-ID')
      if (requestId) {
        options.onRequestId?.(requestId)
      }

      const meta = findOperationMeta(request.method.toUpperCase(), schemaPath)
      const tracksIdempotency = Boolean(meta?.idempotencyKey && idempotencyStore)

      // Тело ошибки читаем из клона только когда оно нужно: для различения
      // 401 `UNAUTHENTICATED` и для решения complete/retain.
      const errorBody =
        !response.ok && (response.status === 401 || tracksIdempotency)
          ? await readResponseBody(response)
          : undefined

      if (response.status === 401) {
        // Различаем недействительную сессию (`UNAUTHENTICATED`) и неверные
        // учётные данные формы входа (`LOGIN_FAILED`). При нечитаемом теле код
        // не подтверждён и очистка не выполняется: ложный logout хуже, чем
        // пропущенный сигнал, который UI всё равно увидит как ошибку.
        if (extractErrorCode(errorBody) === 'UNAUTHENTICATED') {
          emitUnauthorized()
        }
      }

      if (meta?.idempotencyKey && idempotencyStore) {
        const scope = actionScope(params)
        if (response.ok) {
          idempotencyStore.complete(meta.operationId, scope)
        } else {
          const error = toTransportError({ response, error: errorBody })
          if (error.retryable) {
            idempotencyStore.retain(meta.operationId, scope)
          } else {
            idempotencyStore.complete(meta.operationId, scope)
          }
        }
      }

      // 403 и прочие ошибки не повторяются: возвращаем ответ без изменений,
      // чтобы failure не превратился в success.
      return undefined
    },
    onError({ request, schemaPath, params }) {
      // Сетевой сбой не проходит через onResponse: ожидающий ключ нужно явно
      // сохранить, чтобы повтор отправил тот же ключ и тело.
      const meta = findOperationMeta(request.method.toUpperCase(), schemaPath)
      if (meta?.idempotencyKey && idempotencyStore) {
        idempotencyStore.retain(meta.operationId, actionScope(params))
      }
      // Возврат `undefined` оставляет исходную ошибку сети проброшенной.
      return undefined
    },
  }

  client.use(securityMiddleware)
  return client
}
