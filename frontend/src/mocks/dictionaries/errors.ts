// Объявленные контрактом ошибки целей и справочников для управляемых
// mock-сценариев (LT-07.1a).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Каждый код имеет ровно объявленный
// HTTP-статус, контрактный пример и признак `retryable`; выдуманных кодов и
// статусов здесь нет. Mock возвращает тело именно примера (через
// `exampleErrorResponse`), поэтому ошибка остаётся schema-valid и совпадает с
// real-ответом.
//
// Набор ограничен ошибками, объявленными для операций targets/dictionaries
// (API §5/§6/§11): 422 INVALID_TARGET/PATH_OUTSIDE_ROOT/VALIDATION_ERROR,
// 409 DICTIONARY_NAME_CONFLICT/DRAFT_VERSION_CONFLICT. Ошибки 401/403/404
// строятся отдельными хелперами (`responses.ts`), а 429/500/503 не входят в
// управляемый набор этого leaf.

import { exampleErrorResponse } from '../responses'

/** Коды ошибок, воспроизводимые управляемым mock targets/dictionaries. */
export type MockDictionaryErrorCode =
  | 'INVALID_TARGET'
  | 'PATH_OUTSIDE_ROOT'
  | 'DICTIONARY_NAME_CONFLICT'
  | 'DRAFT_VERSION_CONFLICT'
  | 'VALIDATION_ERROR'

/** Описание объявленной ошибки целей/справочников. */
export interface DeclaredDictionaryError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockDictionaryErrorCode
  /** Объявленный HTTP-статус. */
  readonly status: number
  /** Id контрактного примера `contracts/examples/errors/*.json`. */
  readonly exampleId: string
  /** Возможен ли безопасный повтор без изменения условий (API §11). */
  readonly retryable: boolean
}

/** Объявленные ошибки targets/dictionaries из публичных примеров контракта. */
export const declaredDictionaryErrors: Readonly<
  Record<MockDictionaryErrorCode, DeclaredDictionaryError>
> = {
  INVALID_TARGET: {
    code: 'INVALID_TARGET',
    status: 422,
    exampleId: 'error-invalid-target',
    retryable: false,
  },
  PATH_OUTSIDE_ROOT: {
    code: 'PATH_OUTSIDE_ROOT',
    status: 422,
    exampleId: 'error-path-outside-root',
    retryable: false,
  },
  DICTIONARY_NAME_CONFLICT: {
    code: 'DICTIONARY_NAME_CONFLICT',
    status: 409,
    exampleId: 'error-dictionary-name-conflict',
    retryable: false,
  },
  DRAFT_VERSION_CONFLICT: {
    code: 'DRAFT_VERSION_CONFLICT',
    status: 409,
    exampleId: 'error-draft-version-conflict',
    retryable: false,
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    status: 422,
    exampleId: 'error-validation-error',
    retryable: false,
  },
}

/** Проверяет, что значение — объявленный код ошибки targets/dictionaries. */
export function isDictionaryErrorCode(
  value: unknown,
): value is MockDictionaryErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredDictionaryErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки. `request_id`
 * подменяется на безопасный ID текущего mock-ответа; код/сообщение/статус/
 * `retryable` берутся из публичного примера.
 */
export function declaredDictionaryErrorResponse(
  requestId: string,
  code: MockDictionaryErrorCode,
): Response {
  const spec = declaredDictionaryErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
