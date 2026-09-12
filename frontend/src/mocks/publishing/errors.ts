// Объявленные контрактом ошибки публикации/версий/восстановления для
// управляемых mock-сценариев (LT-07.1c).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Каждый код имеет ровно объявленный
// HTTP-статус, контрактный пример и признак `retryable`; выдуманных кодов и
// статусов здесь нет. Mock возвращает тело именно примера (через
// `exampleErrorResponse`), поэтому ошибка остаётся schema-valid и совпадает с
// real-ответом.
//
// Набор ограничен кодами, объявленными для каждой операции:
//  * `publishDictionary`: 409 `DRAFT_VERSION_CONFLICT`, `STALE_SIMULATION`,
//    `RULE_CONFLICT`, `NO_SCENARIO_ACK_REQUIRED`, `IDEMPOTENCY_KEY_REUSED`
//    (OAS 409 = `PublicationConflict`) и 422 `VALIDATION_ERROR`;
//  * `listDictionaryVersions`/`getDictionaryVersion`: 422 `VALIDATION_ERROR`
//    (409 у чтения версий не объявлен);
//  * `restoreDictionaryDraft`: 409 `DRAFT_VERSION_CONFLICT` (OAS 409 =
//    `DraftVersionConflict`) и 422 `VALIDATION_ERROR`.
//
// 401/403/404 строятся отдельными хелперами (`responses.ts`).

import { exampleErrorResponse } from '../responses'

/** Объявленные ошибки `publishDictionary`. */
export type PublishDictionaryErrorCode =
  | 'DRAFT_VERSION_CONFLICT'
  | 'STALE_SIMULATION'
  | 'RULE_CONFLICT'
  | 'NO_SCENARIO_ACK_REQUIRED'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'VALIDATION_ERROR'

/** Объявленные ошибки `listDictionaryVersions`. */
export type ListDictionaryVersionsErrorCode = 'VALIDATION_ERROR'

/** Объявленные ошибки `getDictionaryVersion`. */
export type GetDictionaryVersionErrorCode = 'VALIDATION_ERROR'

/** Объявленные ошибки `restoreDictionaryDraft`. */
export type RestoreDictionaryDraftErrorCode =
  | 'DRAFT_VERSION_CONFLICT'
  | 'VALIDATION_ERROR'

/** Коды ошибок, воспроизводимые управляемым mock публикации/версий/restore. */
export type MockPublishingErrorCode =
  | PublishDictionaryErrorCode
  | ListDictionaryVersionsErrorCode
  | GetDictionaryVersionErrorCode
  | RestoreDictionaryDraftErrorCode

/** Описание объявленной ошибки публикации/версий/восстановления. */
export interface DeclaredPublishingError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockPublishingErrorCode
  /** Объявленный HTTP-статус. */
  readonly status: number
  /** Id контрактного примера `contracts/examples/errors/*.json`. */
  readonly exampleId: string
  /** Возможен ли безопасный повтор без изменения условий (API §11). */
  readonly retryable: boolean
}

/** Объявленные ошибки публикации/версий/восстановления из примеров контракта. */
export const declaredPublishingErrors: Readonly<
  Record<MockPublishingErrorCode, DeclaredPublishingError>
> = {
  DRAFT_VERSION_CONFLICT: {
    code: 'DRAFT_VERSION_CONFLICT',
    status: 409,
    exampleId: 'error-draft-version-conflict',
    retryable: false,
  },
  STALE_SIMULATION: {
    code: 'STALE_SIMULATION',
    status: 409,
    exampleId: 'error-stale-simulation',
    retryable: false,
  },
  RULE_CONFLICT: {
    code: 'RULE_CONFLICT',
    status: 409,
    exampleId: 'error-rule-conflict',
    retryable: false,
  },
  NO_SCENARIO_ACK_REQUIRED: {
    code: 'NO_SCENARIO_ACK_REQUIRED',
    status: 409,
    exampleId: 'error-no-scenario-ack-required',
    retryable: false,
  },
  IDEMPOTENCY_KEY_REUSED: {
    code: 'IDEMPOTENCY_KEY_REUSED',
    status: 409,
    exampleId: 'error-idempotency-key-reused',
    retryable: false,
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    status: 422,
    exampleId: 'error-validation-error',
    retryable: false,
  },
}

/** Проверяет, что значение — объявленный код ошибки публикации/версий. */
export function isPublishingErrorCode(
  value: unknown,
): value is MockPublishingErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredPublishingErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки публикации/версий.
 * `request_id` подменяется на безопасный ID текущего mock-ответа;
 * код/сообщение/статус/`retryable` берутся из публичного примера.
 */
export function declaredPublishingErrorResponse(
  requestId: string,
  code: MockPublishingErrorCode,
): Response {
  const spec = declaredPublishingErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
