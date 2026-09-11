// Объявленные контрактом ошибки сортировки для управляемых mock-сценариев
// очереди и выбора (LT-07.2a).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Каждый код имеет ровно объявленный
// HTTP-статус и признак `retryable`; выдуманных кодов и статусов здесь нет.
//
// Набор строго разделён по операциям (как в LT-07.1b для симуляции):
//
//  * `querySortingQueue` (OAS-ответы 200/401/403/422/429/500/503):
//    `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `VALIDATION_ERROR` 422,
//    `RATE_LIMITED` 429, `INTERNAL_ERROR` 500, `SERVICE_UNAVAILABLE` 503;
//  * `createSortingSelection` (201/401/403/409/422/429/500/503):
//    `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `SELECTION_CHANGED` 409,
//    `VALIDATION_ERROR`/`EMPTY_SELECTION`/`BATCH_LIMIT_EXCEEDED` 422,
//    `RATE_LIMITED` 429, `INTERNAL_ERROR` 500, `SERVICE_UNAVAILABLE` 503.
//
// Важно: 503 обеих операций ссылается на OAS-ответ `ServiceUnavailable`, чей
// enum кода — ТОЛЬКО `SERVICE_UNAVAILABLE`. `SEARCH_UNAVAILABLE` объявлен лишь
// в `SearchUnavailable` для `/search` и `/search/facet` и здесь недопустим.
// Контрактного примера `error-service-unavailable.json` в `contracts/examples`
// нет, поэтому тело 503 синтезируется строго по inline-примеру OAS
// (`ErrorSERVICE_UNAVAILABLE`): безопасное русское сообщение, `retryable:true`,
// `operation_id:null`, пустые `field_errors`.
//
// 401/403 CSRF строятся отдельными хелперами (`guards.ts`/`responses.ts`).
//
// Ошибки использования уже созданного снимка (`FORBIDDEN`/403,
// `SELECTION_EXPIRED`/409, `NOT_FOUND`/404) объявлены для preview/batch, но НЕ
// для `createSortingSelection`; они вынесены в `declaredSelectionUseErrors` и
// применяются резолвером снимка (`selectionUseErrorResponse`). Create их не
// возвращает.

import { errorResponse, exampleErrorResponse } from '../responses'

/** Объявленные ошибки `querySortingQueue`. */
export type QuerySortingQueueErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Объявленные ошибки `createSortingSelection`. */
export type CreateSortingSelectionErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'SELECTION_CHANGED'
  | 'VALIDATION_ERROR'
  | 'EMPTY_SELECTION'
  | 'BATCH_LIMIT_EXCEEDED'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Коды ошибок, воспроизводимые управляемым mock очереди/выбора. */
export type MockSortingErrorCode =
  | QuerySortingQueueErrorCode
  | CreateSortingSelectionErrorCode

/** Операции сортировки, для которых включается управляемая ошибка. */
export type MockSortingOperation =
  | 'querySortingQueue'
  | 'createSortingSelection'

/** Объявленные для каждой операции коды (per-operation restriction). */
export const sortingErrorCodesByOperation: Readonly<
  Record<MockSortingOperation, readonly MockSortingErrorCode[]>
> = {
  querySortingQueue: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
  createSortingSelection: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'SELECTION_CHANGED',
    'VALIDATION_ERROR',
    'EMPTY_SELECTION',
    'BATCH_LIMIT_EXCEEDED',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
}

/**
 * Проверяет, что код объявлен именно для этой операции. Runtime-guard не
 * позволяет выдать undeclared HTTP-статус при обходе типов.
 */
export function isSortingErrorDeclaredForOperation(
  operation: MockSortingOperation,
  code: MockSortingErrorCode,
): boolean {
  return sortingErrorCodesByOperation[operation].includes(code)
}

/** Описание объявленной ошибки сортировки. */
export interface DeclaredSortingError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockSortingErrorCode
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

/**
 * Безопасное сообщение 503 из inline-примера OAS `ErrorSERVICE_UNAVAILABLE`.
 */
const SERVICE_UNAVAILABLE_MESSAGE = 'Сервис временно недоступен.'

/** Объявленные ошибки очереди/выбора из публичных примеров контракта. */
export const declaredSortingErrors: Readonly<
  Record<MockSortingErrorCode, DeclaredSortingError>
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
    exampleId: 'error-forbidden',
    retryable: false,
  },
  SELECTION_CHANGED: {
    code: 'SELECTION_CHANGED',
    status: 409,
    exampleId: 'error-selection-changed',
    retryable: false,
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    status: 422,
    exampleId: 'error-validation-error',
    retryable: false,
  },
  EMPTY_SELECTION: {
    code: 'EMPTY_SELECTION',
    status: 422,
    exampleId: 'error-empty-selection',
    retryable: false,
  },
  BATCH_LIMIT_EXCEEDED: {
    code: 'BATCH_LIMIT_EXCEEDED',
    status: 422,
    exampleId: 'error-batch-limit-exceeded',
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

/** Проверяет, что значение — объявленный код ошибки сортировки. */
export function isSortingErrorCode(
  value: unknown,
): value is MockSortingErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredSortingErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки сортировки.
 * `request_id` подменяется на безопасный ID текущего mock-ответа; для кодов с
 * контрактным примером тело берётся из примера, а `SERVICE_UNAVAILABLE`
 * синтезируется по inline-примеру OAS (`retryable:true`, пустые
 * `field_errors`, `operation_id:null`).
 */
export function declaredSortingErrorResponse(
  requestId: string,
  code: MockSortingErrorCode,
): Response {
  const spec = declaredSortingErrors[code]
  if (spec.exampleId !== null) {
    return exampleErrorResponse(requestId, spec.exampleId, spec.status)
  }
  return errorResponse(requestId, spec.status, {
    code: spec.code,
    message: SERVICE_UNAVAILABLE_MESSAGE,
    retryable: spec.retryable,
  })
}

/** Объявленные ошибки использования снимка (`preview`/`batch`, не `create`). */
export type SelectionUseErrorCode =
  | 'FORBIDDEN'
  | 'SELECTION_EXPIRED'
  | 'NOT_FOUND'

/** Описание объявленной ошибки использования снимка. */
export interface DeclaredSelectionUseError {
  readonly code: SelectionUseErrorCode
  readonly status: number
  readonly exampleId: string
  readonly retryable: boolean
}

/**
 * Ошибки использования снимка: их объявляют `createSortingPreview`/
 * `createSortingBatch`, поэтому они не входят в `declaredSortingErrors`
 * create-операции.
 */
export const declaredSelectionUseErrors: Readonly<
  Record<SelectionUseErrorCode, DeclaredSelectionUseError>
> = {
  FORBIDDEN: {
    code: 'FORBIDDEN',
    status: 403,
    exampleId: 'error-selection-forbidden',
    retryable: false,
  },
  SELECTION_EXPIRED: {
    code: 'SELECTION_EXPIRED',
    status: 409,
    exampleId: 'error-selection-expired-preview',
    retryable: false,
  },
  NOT_FOUND: {
    code: 'NOT_FOUND',
    status: 404,
    exampleId: 'error-selection-not-found',
    retryable: false,
  },
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки использования снимка
 * (`FORBIDDEN` 403, `SELECTION_EXPIRED` 409, `NOT_FOUND` 404).
 */
export function selectionUseErrorResponse(
  requestId: string,
  code: SelectionUseErrorCode,
): Response {
  const spec = declaredSelectionUseErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
