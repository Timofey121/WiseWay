// Объявленные контрактом ошибки партий для управляемых mock-сценариев
// (LT-07.2c).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Набор строго разделён по операциям, как
// в LT-07.1b/LT-07.2a:
//
//  * `createSortingBatch` (202/401/403/404/409/422/429/500/503):
//    `UNAUTHENTICATED` 401, `FORBIDDEN`/`CSRF_FAILED` 403, `NOT_FOUND` 404,
//    `IDEMPOTENCY_KEY_REUSED`/`INVALID_STATE`/`SELECTION_EXPIRED`/
//    `SELECTION_CHANGED`/`STALE_PREVIEW` 409, `VALIDATION_ERROR` 422,
//    `RATE_LIMITED` 429, `INTERNAL_ERROR` 500, `SERVICE_UNAVAILABLE` 503;
//  * `getSortingBatch` (200/401/403/404/422/429/500/503): те же без 409;
//  * `listSortingBatches` (200/401/403/422/429/500/503): те же без 404/409.
//
// Важно: 422 `createSortingBatch` — это OAS `ValidationError`, чей enum кода
// содержит ТОЛЬКО `VALIDATION_ERROR`. Поэтому gate «превышен предел партии»
// отдаёт 422 `VALIDATION_ERROR` с безопасной `field_error`, а НЕ
// `BATCH_LIMIT_EXCEEDED` (тот объявлен только для `createSortingSelection`).
// 503 ссылается на OAS `ServiceUnavailable` (код только
// `SERVICE_UNAVAILABLE`); контрактного файла нет, тело синтезируется по
// inline-примеру OAS.
//
// `FORBIDDEN` и `NOT_FOUND` для create используют batch-примеры
// (`error-batch-forbidden`, `error-batch-selection-not-found`); для чтения —
// общий `error-forbidden` и синтезированный безопасный 404, потому что
// batch-пример описывает именно снимок выбора.

import { errorResponse, exampleErrorResponse, notFoundResponse } from '../responses'

/** Операции партий, для которых включается управляемая ошибка. */
export type MockBatchOperation =
  | 'createSortingBatch'
  | 'getSortingBatch'
  | 'listSortingBatches'

/** Объявленные ошибки `createSortingBatch`. */
export type CreateSortingBatchErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'CSRF_FAILED'
  | 'NOT_FOUND'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'INVALID_STATE'
  | 'SELECTION_EXPIRED'
  | 'SELECTION_CHANGED'
  | 'STALE_PREVIEW'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Объявленные ошибки `getSortingBatch` (409 у чтения отсутствует). */
export type GetSortingBatchErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Объявленные ошибки `listSortingBatches` (404/409 у списка отсутствуют). */
export type ListSortingBatchesErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Коды ошибок, воспроизводимые управляемым mock партий. */
export type MockBatchErrorCode =
  | CreateSortingBatchErrorCode
  | GetSortingBatchErrorCode
  | ListSortingBatchesErrorCode

/** Объявленные для каждой операции коды (per-operation restriction). */
export const batchErrorCodesByOperation: Readonly<
  Record<MockBatchOperation, readonly MockBatchErrorCode[]>
> = {
  createSortingBatch: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'CSRF_FAILED',
    'NOT_FOUND',
    'IDEMPOTENCY_KEY_REUSED',
    'INVALID_STATE',
    'SELECTION_EXPIRED',
    'SELECTION_CHANGED',
    'STALE_PREVIEW',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
  getSortingBatch: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'NOT_FOUND',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
  listSortingBatches: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
}

/**
 * Проверяет, что код объявлен именно для этой операции. Runtime-guard не
 * позволяет выдать undeclared HTTP-статус при обходе типов.
 */
export function isBatchErrorDeclaredForOperation(
  operation: MockBatchOperation,
  code: MockBatchErrorCode,
): boolean {
  return batchErrorCodesByOperation[operation].includes(code)
}

/** Описание объявленной ошибки партии. */
export interface DeclaredBatchError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockBatchErrorCode
  /** Объявленный HTTP-статус. */
  readonly status: number
  /**
   * Id контрактного примера `contracts/examples/errors/*.json`; `null`, если
   * пример объявлен только inline в OAS и синтезируется безопасно.
   */
  readonly exampleId: string | null
  /** Возможен ли безопасный повтор без изменения условий (API §11). */
  readonly retryable: boolean
}

/** Безопасное сообщение 503 из inline-примера OAS `ErrorSERVICE_UNAVAILABLE`. */
const SERVICE_UNAVAILABLE_MESSAGE = 'Сервис временно недоступен.'

/** Объявленные ошибки партий из публичных примеров контракта. */
export const declaredBatchErrors: Readonly<
  Record<MockBatchErrorCode, DeclaredBatchError>
> = {
  UNAUTHENTICATED: {
    code: 'UNAUTHENTICATED',
    status: 401,
    exampleId: 'error-unauthenticated',
    retryable: false,
  },
  FORBIDDEN: {
    code: 'FORBIDDEN',
    status: 403,
    exampleId: 'error-batch-forbidden',
    retryable: false,
  },
  CSRF_FAILED: {
    code: 'CSRF_FAILED',
    status: 403,
    exampleId: 'error-csrf-failed',
    retryable: false,
  },
  NOT_FOUND: {
    code: 'NOT_FOUND',
    status: 404,
    exampleId: 'error-batch-selection-not-found',
    retryable: false,
  },
  IDEMPOTENCY_KEY_REUSED: {
    code: 'IDEMPOTENCY_KEY_REUSED',
    status: 409,
    exampleId: 'error-idempotency-key-reused',
    retryable: false,
  },
  INVALID_STATE: {
    code: 'INVALID_STATE',
    status: 409,
    exampleId: 'error-batch-invalid-state',
    retryable: false,
  },
  SELECTION_EXPIRED: {
    code: 'SELECTION_EXPIRED',
    status: 409,
    exampleId: 'error-batch-selection-expired',
    retryable: false,
  },
  SELECTION_CHANGED: {
    code: 'SELECTION_CHANGED',
    status: 409,
    exampleId: 'error-batch-selection-changed',
    retryable: false,
  },
  STALE_PREVIEW: {
    code: 'STALE_PREVIEW',
    status: 409,
    exampleId: 'error-batch-stale-preview',
    retryable: false,
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    status: 422,
    exampleId: 'error-validation-error',
    retryable: false,
  },
  RATE_LIMITED: {
    code: 'RATE_LIMITED',
    status: 429,
    exampleId: 'error-rate-limited',
    retryable: true,
  },
  INTERNAL_ERROR: {
    code: 'INTERNAL_ERROR',
    status: 500,
    exampleId: 'error-internal-error',
    retryable: false,
  },
  SERVICE_UNAVAILABLE: {
    code: 'SERVICE_UNAVAILABLE',
    status: 503,
    exampleId: null,
    retryable: true,
  },
}

/** Проверяет, что значение — объявленный код ошибки партии. */
export function isBatchErrorCode(value: unknown): value is MockBatchErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredBatchErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки партии. Для
 * `SERVICE_UNAVAILABLE` контрактного файла нет — тело синтезируется по
 * inline-примеру OAS. Для чтения `FORBIDDEN` берётся общий `error-forbidden`,
 * а `NOT_FOUND` синтезируется без деталей: batch-пример описывает снимок
 * выбора, а не партию.
 */
export function batchErrorResponse(
  requestId: string,
  operation: MockBatchOperation,
  code: MockBatchErrorCode,
): Response {
  if (code === 'FORBIDDEN' && operation !== 'createSortingBatch') {
    return exampleErrorResponse(requestId, 'error-forbidden', 403)
  }
  if (code === 'NOT_FOUND' && operation !== 'createSortingBatch') {
    return notFoundResponse(requestId)
  }
  const spec = declaredBatchErrors[code]
  if (spec.exampleId !== null) {
    return exampleErrorResponse(requestId, spec.exampleId, spec.status)
  }
  return errorResponse(requestId, spec.status, {
    code: spec.code,
    message: SERVICE_UNAVAILABLE_MESSAGE,
    retryable: spec.retryable,
  })
}
