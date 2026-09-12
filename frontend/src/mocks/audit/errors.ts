// Объявленные контрактом ошибки журнала аудита для управляемых mock-сценариев
// (LT-07.3b).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/audit/error-audit-validation.json` и
// `contracts/examples/errors/*.json`. Все три операции чтения объявляют один и
// тот же набор статусов (200/401/403/422/429/500/503):
//
//  * `queryAuditEvents`   — 200/401/403/422/429/500/503;
//  * `getAuditUpdates`    — 200/401/403/422/429/500/503;
//  * `listAuditActors`    — 200/401/403/422/429/500/503.
//
// Отсюда объявленные коды: `UNAUTHENTICATED` 401, `FORBIDDEN` 403,
// `VALIDATION_ERROR` 422, `RATE_LIMITED` 429, `INTERNAL_ERROR` 500,
// `SERVICE_UNAVAILABLE` 503. CSRF журналу не объявлен (операции чтения), поэтому
// `CSRF_FAILED` здесь недоступен; 404/409-коды также не объявлены.
//
// Важно: 503 ссылается на OAS-ответ `ServiceUnavailable`, чей enum кода — ТОЛЬКО
// `SERVICE_UNAVAILABLE`; контрактного файла нет, поэтому тело синтезируется по
// inline-примеру OAS. `SEARCH_UNAVAILABLE` объявлен лишь для `/search` и здесь
// недопустим. Для `VALIDATION_ERROR` с ошибкой поля `from` используется
// объявленный пример `error-audit-validation` (код поля `ORDER`); для прочих
// schema-ошибок — общий `error-validation-error`.

import { getExample } from '../data'
import {
  errorResponse,
  exampleErrorResponse,
  validationErrorResponse,
} from '../responses'
import type { ErrorResponse, FieldError } from '../types'

/** Операции журнала, для которых включается управляемая ошибка. */
export type MockAuditOperation =
  | 'queryAuditEvents'
  | 'getAuditUpdates'
  | 'listAuditActors'

/** Объявленные ошибки каждой операции журнала (набор одинаков). */
export type MockAuditErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'SERVICE_UNAVAILABLE'

/** Псевдоним для читаемости: набор кодов ошибок аудита. */
export type AuditErrorCode = MockAuditErrorCode

const AUDIT_ERROR_CODES: readonly MockAuditErrorCode[] = [
  'UNAUTHENTICATED',
  'FORBIDDEN',
  'VALIDATION_ERROR',
  'RATE_LIMITED',
  'INTERNAL_ERROR',
  'SERVICE_UNAVAILABLE',
]

/** Объявленные для каждой операции коды (per-operation restriction). */
export const auditErrorCodesByOperation: Readonly<
  Record<MockAuditOperation, readonly MockAuditErrorCode[]>
> = {
  queryAuditEvents: AUDIT_ERROR_CODES,
  getAuditUpdates: AUDIT_ERROR_CODES,
  listAuditActors: AUDIT_ERROR_CODES,
}

/**
 * Проверяет, что код объявлен именно для этой операции. Runtime-guard не
 * позволяет выдать undeclared HTTP-статус при обходе типов.
 */
export function isAuditErrorDeclaredForOperation(
  operation: MockAuditOperation,
  code: MockAuditErrorCode,
): boolean {
  return auditErrorCodesByOperation[operation].includes(code)
}

/** Описание объявленной ошибки журнала. */
export interface DeclaredAuditError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockAuditErrorCode
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

/** Объявленные ошибки журнала из публичных примеров контракта. */
export const declaredAuditErrors: Readonly<
  Record<MockAuditErrorCode, DeclaredAuditError>
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

/** Проверяет, что значение — объявленный код ошибки журнала. */
export function isAuditErrorCode(value: unknown): value is MockAuditErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredAuditErrors, value)
  )
}

/** Опции построения объявленной ошибки журнала. */
export interface AuditErrorOptions {
  /** Безопасные ошибки полей для `VALIDATION_ERROR`. */
  readonly fieldErrors?: readonly FieldError[]
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки журнала. `request_id`
 * подменяется на безопасный ID текущего mock-ответа. Для `VALIDATION_ERROR` с
 * ошибкой интервала (`from`/`to`) используется объявленный пример
 * `error-audit-validation`; для `SERVICE_UNAVAILABLE` контрактного файла нет —
 * тело синтезируется по inline-примеру OAS.
 */
export function auditErrorResponse(
  requestId: string,
  operation: MockAuditOperation,
  code: MockAuditErrorCode,
  options: AuditErrorOptions = {},
): Response {
  if (!isAuditErrorDeclaredForOperation(operation, code)) {
    // Runtime-guard: undeclared для операции код не отдаётся как HTTP-статус.
    return errorResponse(requestId, 500, {
      code: 'INTERNAL_ERROR',
      message: 'Внутренняя ошибка.',
      retryable: false,
    })
  }
  if (code === 'VALIDATION_ERROR') {
    const fieldErrors = options.fieldErrors ?? []
    if (
      fieldErrors.some(
        (item) => item.field === 'from' || item.field === 'to',
      )
    ) {
      const example = getExample<ErrorResponse>('error-audit-validation')
      return errorResponse(requestId, 422, {
        code: 'VALIDATION_ERROR',
        message: example.error.message,
        retryable: example.error.retryable,
        fieldErrors: [...fieldErrors],
      })
    }
    return validationErrorResponse(requestId, [...fieldErrors])
  }
  const spec = declaredAuditErrors[code]
  if (spec.exampleId !== null) {
    return exampleErrorResponse(requestId, spec.exampleId, spec.status)
  }
  return errorResponse(requestId, spec.status, {
    code: spec.code,
    message: SERVICE_UNAVAILABLE_MESSAGE,
    retryable: spec.retryable,
  })
}
