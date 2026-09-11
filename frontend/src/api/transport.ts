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
//   `#/components/parameters/IdempotencyKey` и только если ключ предоставлен
//   провайдером (in-memory хранилище — LT-05.2a). Иначе фиктивная
//   идемпотентность не появляется;
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
import { emitUnauthorized, getCsrfToken } from './session-context'

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
  /** Провайдер Idempotency-Key для объявленных идемпотентных операций. */
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
 * Читает `error.code` из тела ответа через `Response.clone()`, не расходуя
 * оригинальное тело, которое далее читает `openapi-fetch`. Возвращает `null`,
 * если тела нет, оно не JSON или код отсутствует.
 */
async function readErrorCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.clone().json()
    if (body && typeof body === 'object') {
      const error = (body as { error?: unknown }).error
      if (error && typeof error === 'object') {
        const code = (error as { code?: unknown }).code
        if (typeof code === 'string') {
          return code
        }
      }
    }
  } catch {
    // Тело отсутствует или не является JSON — код определить нельзя.
  }
  return null
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

  const client = createClient<paths>({ baseUrl, fetch: fetchImpl })

  const securityMiddleware: Middleware = {
    onRequest({ request, schemaPath }) {
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

        const idempotencyKey = meta.idempotencyKey
          ? options.idempotencyKeyProvider?.(context)
          : null
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
    async onResponse({ response }) {
      const requestId = response.headers.get('X-Request-ID')
      if (requestId) {
        options.onRequestId?.(requestId)
      }
      if (response.status === 401) {
        // Различаем недействительную сессию (`UNAUTHENTICATED`) и неверные
        // учётные данные формы входа (`LOGIN_FAILED`). Тело читаем из клона,
        // поэтому оригинал остаётся доступен `openapi-fetch`. При нечитаемом
        // теле код не подтверждён и очистка не выполняется: ложный logout
        // хуже, чем пропущенный сигнал, который UI всё равно увидит как ошибку.
        const code = await readErrorCode(response)
        if (code === 'UNAUTHENTICATED') {
          emitUnauthorized()
        }
      }
      // 403 и прочие ошибки не повторяются: возвращаем ответ без изменений,
      // чтобы failure не превратился в success.
      return undefined
    },
  }

  client.use(securityMiddleware)
  return client
}
