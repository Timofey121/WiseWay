// Построение mock-ответов с контрактными заголовками.
//
// Все успешные ответы — JSON + `Content-Type: application/json`; каждый ответ
// несёт безопасный `X-Request-ID` (в ошибке совпадает с `error.request_id`), а
// пользовательские ответы — `Cache-Control: no-store` (API §2). Ошибки
// строятся по контрактным примерам `contracts/examples/errors/*.json`, поэтому
// сообщения и коды совпадают с публичным контрактом.
//
// Дополнительный заголовок `X-WiseWay-Mock` явно помечает ответ как mock:
// инфраструктура не является защищённым auth backend и не заменяет сервер.

import { getExample } from './data'
import type { ErrorCode, ErrorResponse, FieldError } from './types'

/** Маркер mock-режима для заголовков/тестов. */
export const MOCK_MODE = 'mock' as const

/** Заголовок, помечающий ответ как выданный mock-инфраструктурой. */
export const MOCK_MARKER_HEADER = 'X-WiseWay-Mock'

/** Статус единственного контрактного сценария, требующего `Retry-After`. */
const RATE_LIMITED_STATUS = 429

/** Контрактный заголовок `components.headers.RetryAfter`. */
export const RETRY_AFTER_HEADER = 'Retry-After'

/**
 * Контрактное значение `Retry-After` первой версии OAS: delta-seconds
 * (`^[0-9]+$`), совпадающее с примером `components.headers.RetryAfter`.
 */
export const RETRY_AFTER_SECONDS = '30'

function responseHeaders(
  requestId: string,
  json: boolean,
  status: number,
): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Request-ID': requestId,
    'Cache-Control': 'no-store',
    [MOCK_MARKER_HEADER]: MOCK_MODE,
  }
  if (json) {
    headers['Content-Type'] = 'application/json'
  }
  // 429 в OAS отображается только на `RateLimited`, поэтому `Retry-After`
  // добавляется здесь, в едином общем пути, и не дублируется в handlers.
  if (status === RATE_LIMITED_STATUS) {
    headers[RETRY_AFTER_HEADER] = RETRY_AFTER_SECONDS
  }
  return headers
}

/** JSON-ответ 200/2xx со стандартными контрактными заголовками. */
export function jsonResponse(
  body: unknown,
  requestId: string,
  status = 200,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: responseHeaders(requestId, true, status),
  })
}

/** Ответ 204 без тела (logout). */
export function noContentResponse(requestId: string): Response {
  return new Response(null, {
    status: 204,
    headers: responseHeaders(requestId, false, 204),
  })
}

interface ErrorResponseSpec {
  code: ErrorCode
  message: string
  retryable?: boolean
  fieldErrors?: FieldError[]
  operationId?: string | null
}

/** Безопасный `ErrorResponse` контракта. */
export function errorResponse(
  requestId: string,
  status: number,
  spec: ErrorResponseSpec,
): Response {
  const body: ErrorResponse = {
    error: {
      code: spec.code,
      message: spec.message,
      request_id: requestId,
      operation_id: spec.operationId ?? null,
      retryable: spec.retryable ?? false,
      field_errors: spec.fieldErrors ?? [],
    },
  }
  return jsonResponse(body, requestId, status)
}

/**
 * Строит ошибку из контрактного примера `contracts/examples/errors/*.json`,
 * подменяя `request_id` на безопасный идентификатор текущего mock-ответа.
 */
function fromErrorExample(
  requestId: string,
  status: number,
  exampleId: string,
  fieldErrors?: FieldError[],
): Response {
  const example = getExample<ErrorResponse>(exampleId)
  return errorResponse(requestId, status, {
    code: example.error.code,
    message: example.error.message,
    retryable: example.error.retryable,
    fieldErrors: fieldErrors ?? example.error.field_errors,
  })
}

/**
 * Ответ-ошибка ровно из объявленного контрактного примера
 * `contracts/examples/errors/*.json` со статусом вызывающей стороны и
 * безопасным `request_id` текущего mock-ответа.
 *
 * Используется управляемыми error-сценариями (LT-06.2b): код, сообщение и
 * `retryable` берутся из публичного примера, а не выдумываются, поэтому
 * mock-ошибка совпадает с контрактом.
 */
export function exampleErrorResponse(
  requestId: string,
  exampleId: string,
  status: number,
): Response {
  return fromErrorExample(requestId, status, exampleId)
}

/** 401 LOGIN_FAILED — единая ошибка формы входа. */
export function loginFailedResponse(requestId: string): Response {
  return fromErrorExample(requestId, 401, 'error-login-failed')
}

/** 401 UNAUTHENTICATED — сессия отсутствует или истекла. */
export function unauthenticatedResponse(requestId: string): Response {
  return fromErrorExample(requestId, 401, 'error-unauthenticated')
}

/** 403 CSRF_FAILED — неверный/отсутствующий X-CSRF-Token. */
export function csrfFailedResponse(requestId: string): Response {
  return fromErrorExample(requestId, 403, 'error-csrf-failed')
}

/** 422 VALIDATION_ERROR с безопасными ошибками полей. */
export function validationErrorResponse(
  requestId: string,
  fieldErrors: FieldError[],
): Response {
  return fromErrorExample(requestId, 422, 'error-validation-error', fieldErrors)
}

/** 422 VALIDATION_ERROR для пустого/битого JSON-тела без эха значений. */
export function invalidBodyResponse(requestId: string): Response {
  return validationErrorResponse(requestId, [
    {
      field: 'request',
      code: 'INVALID_BODY',
      message: 'Тело запроса должно быть корректным JSON.',
    },
  ])
}

/**
 * 400 INVALID_QUERY — объявленная контрактом безопасная ошибка поиска.
 * Используется, когда запрос валиден по схеме, но literal golden-сценарий для
 * него не объявлен: mock не выполняет matcher/ranking и не выдумывает успех.
 */
export function invalidQueryResponse(requestId: string): Response {
  return fromErrorExample(requestId, 400, 'error-invalid-query')
}

/** Безопасное сообщение 404 без выдуманных деталей. */
const NOT_FOUND_MESSAGE = 'Объект не найден.'

/** 404 NOT_FOUND для неизвестного mock-маршрута. */
export function notFoundResponse(requestId: string): Response {
  return errorResponse(requestId, 404, {
    code: 'NOT_FOUND',
    message: NOT_FOUND_MESSAGE,
  })
}
