// Объявленные контрактом ошибки сортировки для управляемых mock-сценариев
// очереди, выбора и preview (LT-07.2a/07.2b).
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
//    `RATE_LIMITED` 429, `INTERNAL_ERROR` 500, `SERVICE_UNAVAILABLE` 503;
//  * `createSortingPreview` (201/401/403/404/409/422/429/500/503):
//    `UNAUTHENTICATED`/`FORBIDDEN`/`NOT_FOUND`/`SELECTION_EXPIRED`/
//    `SELECTION_CHANGED`/`INVALID_STATE`/`VALIDATION_ERROR`/`RATE_LIMITED`/
//    `INTERNAL_ERROR`/`SERVICE_UNAVAILABLE`;
//  * `getSortingPreview` (200/401/403/404/422/429/500/503): те же без 409
//    (`SELECTION_EXPIRED`/`SELECTION_CHANGED`/`INVALID_STATE`).
//
// Важно: 503 всех операций ссылается на OAS-ответ `ServiceUnavailable`, чей
// enum кода — ТОЛЬКО `SERVICE_UNAVAILABLE`. `SEARCH_UNAVAILABLE` объявлен лишь
// в `SearchUnavailable` для `/search` и `/search/facet` и здесь недопустим.
// Контрактного примера `error-service-unavailable.json` в `contracts/examples`
// нет, поэтому тело 503 синтезируется строго по inline-примеру OAS
// (`ErrorSERVICE_UNAVAILABLE`): безопасное русское сообщение, `retryable:true`,
// `operation_id:null`, пустые `field_errors`.
//
// `STALE_PREVIEW` объявлен только для `createSortingBatch` (LT-07.2c) и
// доступен через `declaredSelectionUseErrors`, но не входит ни в один
// preview-набор, поэтому preview create/get его не возвращают.
//
// 401/403 CSRF строятся отдельными хелперами (`guards.ts`/`responses.ts`).
//
// Ошибки использования уже созданного снимка (`FORBIDDEN`/403,
// `SELECTION_EXPIRED`/409, `NOT_FOUND`/404) объявлены для preview/batch, но НЕ
// для `createSortingSelection`; они вынесены в `declaredSelectionUseErrors` и
// применяются резолвером снимка (`selectionUseErrorResponse`). Create их не
// возвращает. Для preview эти же коды (плюс `INVALID_STATE`/
// `SELECTION_CHANGED`) собраны в `declaredPreviewErrors` с preview-примерами.

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

/**
 * Объявленные ошибки `createSortingPreview` (OAS 201/401/403/404/409/422/429/
 * 500/503). 409 = `PreviewConflict` (`SELECTION_EXPIRED`, `SELECTION_CHANGED`,
 * `INVALID_STATE`). `STALE_PREVIEW` этой операцией НЕ объявлен.
 */
export type CreateSortingPreviewErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'SELECTION_EXPIRED'
  | 'SELECTION_CHANGED'
  | 'INVALID_STATE'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/**
 * Объявленные ошибки `getSortingPreview` (OAS 200/401/403/404/422/429/500/503).
 * 409 у чтения отсутствует, поэтому `SELECTION_*`/`INVALID_STATE` не входят.
 */
export type GetSortingPreviewErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Коды ошибок preview, воспроизводимые управляемым mock (LT-07.2b). */
export type MockPreviewErrorCode =
  | CreateSortingPreviewErrorCode
  | GetSortingPreviewErrorCode

/** Операции сортировки, для которых включается управляемая ошибка. */
export type MockSortingOperation =
  | 'querySortingQueue'
  | 'createSortingSelection'
  | 'createSortingPreview'
  | 'getSortingPreview'

/** Preview-операции, для которых включается управляемая ошибка (LT-07.2b). */
export type MockPreviewOperation = 'createSortingPreview' | 'getSortingPreview'

/** Коды каталога queue/selection (`declaredSortingErrors`). */
export type QueueSelectionSortingErrorCode =
  | QuerySortingQueueErrorCode
  | CreateSortingSelectionErrorCode

/** Коды ошибок, воспроизводимые управляемым mock сортировки. */
export type MockSortingErrorCode =
  | QueueSelectionSortingErrorCode
  | MockPreviewErrorCode

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
  createSortingPreview: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'NOT_FOUND',
    'SELECTION_EXPIRED',
    'SELECTION_CHANGED',
    'INVALID_STATE',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
  getSortingPreview: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'NOT_FOUND',
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
  Record<QueueSelectionSortingErrorCode, DeclaredSortingError>
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

/**
 * Объявленные ошибки preview из публичных примеров контракта. `FORBIDDEN`,
 * `SELECTION_EXPIRED`, `NOT_FOUND` — ошибки использования снимка (owner/expiry/
 * unknown); `SELECTION_CHANGED`/`INVALID_STATE` — 409 `PreviewConflict`;
 * `SERVICE_UNAVAILABLE` синтезируется по inline-примеру OAS.
 */
export const declaredPreviewErrors: Readonly<
  Record<MockPreviewErrorCode, DeclaredSortingError>
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
    exampleId: 'error-selection-forbidden',
    retryable: false,
  },
  NOT_FOUND: {
    code: 'NOT_FOUND',
    status: 404,
    exampleId: 'error-selection-not-found',
    retryable: false,
  },
  SELECTION_EXPIRED: {
    code: 'SELECTION_EXPIRED',
    status: 409,
    exampleId: 'error-preview-selection-expired',
    retryable: false,
  },
  SELECTION_CHANGED: {
    code: 'SELECTION_CHANGED',
    status: 409,
    exampleId: 'error-preview-selection-changed',
    retryable: false,
  },
  INVALID_STATE: {
    code: 'INVALID_STATE',
    status: 409,
    // Единственный контрактный пример с кодом INVALID_STATE; inline-пример OAS
    // `ErrorINVALID_STATE` несёт то же безопасное сообщение.
    exampleId: 'error-batch-invalid-state',
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

/** Проверяет, что значение — объявленный код ошибки preview. */
export function isPreviewErrorCode(
  value: unknown,
): value is MockPreviewErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredPreviewErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки preview. Для
 * `SERVICE_UNAVAILABLE` контрактного файла нет — тело синтезируется по
 * inline-примеру OAS `ErrorSERVICE_UNAVAILABLE`.
 */
export function previewErrorResponse(
  requestId: string,
  code: MockPreviewErrorCode,
): Response {
  const spec = declaredPreviewErrors[code]
  if (spec.exampleId !== null) {
    return exampleErrorResponse(requestId, spec.exampleId, spec.status)
  }
  return errorResponse(requestId, spec.status, {
    code: spec.code,
    message: SERVICE_UNAVAILABLE_MESSAGE,
    retryable: spec.retryable,
  })
}

/** Проверяет, что значение — объявленный код ошибки сортировки. */
export function isSortingErrorCode(
  value: unknown,
): value is MockSortingErrorCode {
  return (
    typeof value === 'string' &&
    (Object.prototype.hasOwnProperty.call(declaredSortingErrors, value) ||
      Object.prototype.hasOwnProperty.call(declaredPreviewErrors, value))
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки сортировки.
 * `request_id` подменяется на безопасный ID текущего mock-ответа; для кодов с
 * контрактным примером тело берётся из примера, а `SERVICE_UNAVAILABLE`
 * синтезируется по inline-примеру OAS (`retryable:true`, пустые
 * `field_errors`, `operation_id:null`). Preview-коды делегируются
 * `previewErrorResponse`.
 */
export function declaredSortingErrorResponse(
  requestId: string,
  code: MockSortingErrorCode,
): Response {
  if (isPreviewErrorCode(code)) {
    return previewErrorResponse(requestId, code)
  }
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

/**
 * Объявленные ошибки использования снимка (`preview`/`batch`, не `create`).
 * `STALE_PREVIEW` объявлен только для `createSortingBatch` (`BatchConflict`) и
 * доступен инфраструктуре LT-07.2c, но не входит в набор preview-операций.
 */
export type SelectionUseErrorCode =
  | 'FORBIDDEN'
  | 'SELECTION_EXPIRED'
  | 'NOT_FOUND'
  | 'STALE_PREVIEW'

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
 * create-операции. `STALE_PREVIEW` объявляет только `createSortingBatch`
 * (LT-07.2c): preview create/get его не возвращают, потому что он не входит в
 * их per-operation наборы.
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
  STALE_PREVIEW: {
    code: 'STALE_PREVIEW',
    status: 409,
    exampleId: 'error-batch-stale-preview',
    retryable: false,
  },
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки использования снимка
 * (`FORBIDDEN` 403, `SELECTION_EXPIRED` 409, `NOT_FOUND` 404, `STALE_PREVIEW`
 * 409 для LT-07.2c).
 */
export function selectionUseErrorResponse(
  requestId: string,
  code: SelectionUseErrorCode,
): Response {
  const spec = declaredSelectionUseErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
