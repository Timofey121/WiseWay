// Объявленные контрактом ошибки симуляции для управляемых mock-сценариев
// (LT-07.1b).
//
// Единственный источник истины — публичный OAS и примеры
// `contracts/examples/errors/*.json`. Каждый код имеет ровно объявленный
// HTTP-статус, контрактный пример и признак `retryable`; выдуманных кодов и
// статусов здесь нет. Mock возвращает тело именно примера (через
// `exampleErrorResponse`), поэтому ошибка остаётся schema-valid и совпадает с
// real-ответом.
//
// Набор ограничен кодами, объявленными для каждой операции:
//  * `createDictionarySimulation`: 409 `DRAFT_VERSION_CONFLICT` (OAS 409 =
//    `DraftVersionConflict`; literal-фикстура `dictionary_lifecycle.json` →
//    `simulate-stale-draft`) и 422 `VALIDATION_ERROR`;
//  * `getSimulation`: 422 `VALIDATION_ERROR` (409 у операции не объявлен).
//
// `STALE_SIMULATION` объявлен только для `publishDictionary` и в набор
// симуляции не входит: staleness созданного результата — предмет publish
// (LT-07.1c), а не create/get. 401/403/404 строятся отдельными хелперами
// (`responses.ts`).

import { exampleErrorResponse } from '../responses'

/** Объявленные ошибки `createDictionarySimulation`. */
export type CreateDictionarySimulationErrorCode =
  | 'DRAFT_VERSION_CONFLICT'
  | 'VALIDATION_ERROR'

/** Объявленные ошибки `getSimulation` (409 у операции отсутствует). */
export type GetSimulationErrorCode = 'VALIDATION_ERROR'

/** Коды ошибок, воспроизводимые управляемым mock симуляции. */
export type MockSimulationErrorCode =
  | CreateDictionarySimulationErrorCode
  | GetSimulationErrorCode

/** Описание объявленной ошибки симуляции. */
export interface DeclaredSimulationError {
  /** Код из `ErrorCode` публичного OAS. */
  readonly code: MockSimulationErrorCode
  /** Объявленный HTTP-статус. */
  readonly status: number
  /** Id контрактного примера `contracts/examples/errors/*.json`. */
  readonly exampleId: string
  /** Возможен ли безопасный повтор без изменения условий (API §11). */
  readonly retryable: boolean
}

/** Объявленные ошибки симуляции из публичных примеров контракта. */
export const declaredSimulationErrors: Readonly<
  Record<MockSimulationErrorCode, DeclaredSimulationError>
> = {
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

/** Проверяет, что значение — объявленный код ошибки симуляции. */
export function isSimulationErrorCode(
  value: unknown,
): value is MockSimulationErrorCode {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(declaredSimulationErrors, value)
  )
}

/**
 * Строит контрактный `ErrorResponse` объявленной ошибки симуляции.
 * `request_id` подменяется на безопасный ID текущего mock-ответа;
 * код/сообщение/статус/`retryable` берутся из публичного примера.
 */
export function declaredSimulationErrorResponse(
  requestId: string,
  code: MockSimulationErrorCode,
): Response {
  const spec = declaredSimulationErrors[code]
  return exampleErrorResponse(requestId, spec.exampleId, spec.status)
}
