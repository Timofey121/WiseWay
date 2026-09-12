// Объявленные контрактом ошибки карантина для управляемых mock-сценариев
// (LT-07.3a).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Набор строго разделён по операциям:
//
//  * `listQuarantineItems` (OAS 200/401/403/422/429/500/503):
//    `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `VALIDATION_ERROR` 422,
//    `RATE_LIMITED` 429, `INTERNAL_ERROR` 500, `SERVICE_UNAVAILABLE` 503;
//  * `returnQuarantineItem` (OAS 200/401/403/404/409/422/429/500/503):
//    `UNAUTHENTICATED` 401, `FORBIDDEN`/`CSRF_FAILED` 403, `NOT_FOUND` 404,
//    `IDEMPOTENCY_KEY_REUSED`/`QUARANTINE_VERSION_CONFLICT`/
//    `ORIGINAL_PATH_OCCUPIED`/`INVALID_STATE`/`RECOVERY_REQUIRED` 409,
//    `VALIDATION_ERROR` 422, `RATE_LIMITED` 429, `INTERNAL_ERROR` 500,
//    `SERVICE_UNAVAILABLE` 503.
//
// Важно: 503 обеих операций ссылается на OAS-ответ `ServiceUnavailable`, чей
// enum кода — ТОЛЬКО `SERVICE_UNAVAILABLE`; контрактного файла нет, поэтому
// тело синтезируется по inline-примеру OAS. `SEARCH_UNAVAILABLE` объявлен лишь
// для `/search` и здесь недопустим.
//
// `RECOVERY_REQUIRED` несёт динамический `error.operation_id`: зарегистрированную
// операцию возврата из конкретной записи карантина (API §9), а не константу
// примера. `VALIDATION_ERROR` для комментария берётся из
// `error-quarantine-comment-validation` (field `comment`), для прочих
// schema-ошибок — общий `error-validation-error`.

import { getExample } from '../data'
import {
  errorResponse,
  exampleErrorResponse,
  validationErrorResponse,
} from '../responses'
import type { ErrorResponse, FieldError } from '../types'

/** Операции карантина, для которых включается управляемая ошибка. */
export type MockQuarantineOperation =
  | 'listQuarantineItems'
  | 'returnQuarantineItem'

/** Объявленные ошибки `listQuarantineItems`. */
export type ListQuarantineItemsErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Объявленные ошибки `returnQuarantineItem`. */
export type ReturnQuarantineItemErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'CSRF_FAILED'
  | 'NOT_FOUND'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'QUARANTINE_VERSION_CONFLICT'
  | 'ORIGINAL_PATH_OCCUPIED'
  | 'INVALID_STATE'
  | 'RECOVERY_REQUIRED'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Коды ошибок, воспроизводимые управляемым mock карантина. */
export type MockQuarantineErrorCode =
  | ListQuarantineItemsErrorCode
  | ReturnQuarantineItemErrorCode

/** Объявленные для каждой операции коды (per-operation restriction). */
export const quarantineErrorCodesByOperation: Readonly<
  Record<MockQuarantineOperation, readonly MockQuarantineErrorCode[]>
> = {
  listQuarantineItems: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'VALIDATION_ERROR',
    'RATE_LIMITED',
    'INTERNAL_ERROR',
    'SERVICE_UNAVAILABLE',
  ],
  returnQuarantineItem: [
    'UNAUTHENTICATED',
    'FORBIDDEN',
    'CSRF_FAILED',
    'NOT_FOUND',
    'IDEMPOTENCY_KEY_REUSED',
    'QUARANTINE_VERSION_CONFLICT',
    'ORIGINAL_PATH_OCCUPIED',
    'INVALID_STATE',
    'RECOVERY_REQUIRED',
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
export function isQuarantineErrorDeclaredForOperation(
  operation: MockQuarantineOperation,
  code: MockQuarantineErrorCode,
): boolean {
  return quarantineErrorCodesByOperation[operation].includes(code)
}

/** Описание объявленной ошибки карантина. */
export interface DeclaredQuarantineError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockQuarantineErrorCode
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

/** Объявленные ошибки карантина из публичных примеров контракта. */
export const declaredQuarantineErrors: Readonly<
  Record<MockQuarantineErrorCode, DeclaredQuarantineError>
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
  CSRF_FAILED: {
    code: 'CSRF_FAILED',
    status: 403,
    exampleId: 'error-csrf-failed',
    retryable: false,
  },
  NOT_FOUND: {
    code: 'NOT_FOUND',
    status: 404,
    exampleId: 'error-quarantine-not-found',
    retryable: false,
  },
  IDEMPOTENCY_KEY_REUSED: {
    code: 'IDEMPOTENCY_KEY_REUSED',
    status: 409,
    exampleId: 'error-quarantine-idempotency-key-reused',
    retryable: false,
  },
  QUARANTINE_VERSION_CONFLICT: {
    code: 'QUARANTINE_VERSION_CONFLICT',
    status: 409,
    exampleId: 'error-quarantine-version-conflict',
    retryable: false,
  },
  ORIGINAL_PATH_OCCUPIED: {
    code: 'ORIGINAL_PATH_OCCUPIED',
    status: 409,
    exampleId: 'error-original-path-occupied',
    retryable: false,
  },
  INVALID_STATE: {
    code: 'INVALID_STATE',
    status: 409,
    exampleId: 'error-quarantine-invalid-state',
    retryable: false,
  },
  RECOVERY_REQUIRED: {
    code: 'RECOVERY_REQUIRED',
    status: 409,
    exampleId: 'error-quarantine-recovery-required',
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

/** Проверяет, что значение — объявленный код ошибки карантина. */
export function isQuarantineErrorCode(
  value: unknown,
): value is MockQuarantineErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredQuarantineErrors, value)
  )
}

/**
 * Строит `ErrorResponse` `RECOVERY_REQUIRED` с зарегистрированным
 * `error.operation_id` из конкретной записи карантина (API §9). Сообщение и
 * `retryable` берутся из контрактного примера
 * `error-quarantine-recovery-required`; подменяется только безопасный
 * `request_id` и `operation_id`.
 */
export function recoveryRequiredResponse(
  requestId: string,
  operationId: string | null,
): Response {
  const example = getExample<ErrorResponse>('error-quarantine-recovery-required')
  return errorResponse(requestId, 409, {
    code: 'RECOVERY_REQUIRED',
    message: example.error.message,
    operationId,
    retryable: example.error.retryable,
  })
}

/** Опции построения объявленной ошибки карантина. */
export interface QuarantineErrorOptions {
  /** Зарегистрированная операция для `RECOVERY_REQUIRED`. */
  readonly operationId?: string | null
  /** Безопасные ошибки полей для `VALIDATION_ERROR`. */
  readonly fieldErrors?: readonly FieldError[]
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки карантина.
 * `request_id` подменяется на безопасный ID текущего mock-ответа. Для
 * `RECOVERY_REQUIRED` обязателен зарегистрированный `operationId`; для
 * `SERVICE_UNAVAILABLE` контрактного файла нет — тело синтезируется по
 * inline-примеру OAS.
 */
export function quarantineErrorResponse(
  requestId: string,
  operation: MockQuarantineOperation,
  code: MockQuarantineErrorCode,
  options: QuarantineErrorOptions = {},
): Response {
  if (!isQuarantineErrorDeclaredForOperation(operation, code)) {
    // Runtime-guard: undeclared для операции код не отдаётся как HTTP-статус.
    return errorResponse(requestId, 500, {
      code: 'INTERNAL_ERROR',
      message: 'Внутренняя ошибка.',
      retryable: false,
    })
  }
  if (code === 'RECOVERY_REQUIRED') {
    return recoveryRequiredResponse(requestId, options.operationId ?? null)
  }
  if (code === 'VALIDATION_ERROR') {
    const fieldErrors = options.fieldErrors ?? []
    if (fieldErrors.some((item) => item.field === 'comment')) {
      // Комментарий возврата — отдельный объявленный пример контракта.
      const example = getExample<ErrorResponse>(
        'error-quarantine-comment-validation',
      )
      return errorResponse(requestId, 422, {
        code: 'VALIDATION_ERROR',
        message: example.error.message,
        retryable: example.error.retryable,
        fieldErrors: [...fieldErrors],
      })
    }
    return validationErrorResponse(requestId, [...fieldErrors])
  }
  const spec = declaredQuarantineErrors[code]
  if (spec.exampleId !== null) {
    return exampleErrorResponse(requestId, spec.exampleId, spec.status)
  }
  return errorResponse(requestId, spec.status, {
    code: spec.code,
    message: SERVICE_UNAVAILABLE_MESSAGE,
    retryable: spec.retryable,
  })
}
