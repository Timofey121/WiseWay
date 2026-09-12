// Объявленные контрактом ошибки поиска для управляемых mock-сценариев
// (LT-06.2b).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Каждый код имеет ровно объявленный
// HTTP-статус, контрактный пример и признак `retryable`; выдуманных кодов и
// статусов здесь нет. Mock возвращает тело именно примера (через
// `exampleErrorResponse`), поэтому ошибка остаётся schema-valid и совпадает с
// real-ответом.
//
// Набор ограничен ошибками, объявленными для `searchFiles`/`getSearchFacet`
// (API §4/§11): 400 INVALID_QUERY, 422 VALIDATION_ERROR/INVALID_MARKER_SELECTION,
// 409 SCHEMA_VERSION_CHANGED/ROOT_NOT_READY, 429 RATE_LIMITED,
// 503 SEARCH_UNAVAILABLE, 500 INTERNAL_ERROR.

import { exampleErrorResponse } from '../responses'

/** Коды ошибок, воспроизводимые управляемым mock-поиском. */
export type SearchErrorCode =
  | 'INVALID_QUERY'
  | 'VALIDATION_ERROR'
  | 'INVALID_MARKER_SELECTION'
  | 'SCHEMA_VERSION_CHANGED'
  | 'ROOT_NOT_READY'
  | 'RATE_LIMITED'
  | 'SEARCH_UNAVAILABLE'
  | 'INTERNAL_ERROR'

/** Описание объявленной ошибки поиска. */
export interface DeclaredSearchError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: SearchErrorCode
  /** Объявленный HTTP-статус. */
  readonly status: number
  /** Id контрактного примера `contracts/examples/errors/*.json`. */
  readonly exampleId: string
  /** Возможен ли безопасный повтор без изменения условий (API §11). */
  readonly retryable: boolean
}

/**
 * Объявленные ошибки поиска. Значения согласованы с
 * `fixtures/synthetic/search_expectations.json` → `error_scenarios`.
 */
export const declaredSearchErrors: Readonly<
  Record<SearchErrorCode, DeclaredSearchError>
> = {
  INVALID_QUERY: {
    code: 'INVALID_QUERY',
    status: 400,
    exampleId: 'error-invalid-query',
    retryable: false,
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    status: 422,
    exampleId: 'error-validation-error',
    retryable: false,
  },
  INVALID_MARKER_SELECTION: {
    code: 'INVALID_MARKER_SELECTION',
    status: 422,
    exampleId: 'error-invalid-marker-selection',
    retryable: false,
  },
  SCHEMA_VERSION_CHANGED: {
    code: 'SCHEMA_VERSION_CHANGED',
    status: 409,
    exampleId: 'error-schema-version-changed',
    retryable: false,
  },
  ROOT_NOT_READY: {
    code: 'ROOT_NOT_READY',
    status: 409,
    exampleId: 'error-root-not-ready',
    retryable: false,
  },
  RATE_LIMITED: {
    code: 'RATE_LIMITED',
    status: 429,
    exampleId: 'error-rate-limited',
    retryable: true,
  },
  SEARCH_UNAVAILABLE: {
    code: 'SEARCH_UNAVAILABLE',
    status: 503,
    exampleId: 'error-search-unavailable',
    retryable: true,
  },
  INTERNAL_ERROR: {
    code: 'INTERNAL_ERROR',
    status: 500,
    exampleId: 'error-internal-error',
    retryable: false,
  },
}

/** Проверяет, что значение — объявленный код ошибки поиска. */
export function isSearchErrorCode(value: unknown): value is SearchErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredSearchErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки поиска. `request_id`
 * подменяется на безопасный ID текущего mock-ответа; код/сообщение/статус/
 * `retryable` берутся из публичного примера.
 */
export function declaredSearchErrorResponse(
  requestId: string,
  code: SearchErrorCode,
): Response {
  const spec = declaredSearchErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
