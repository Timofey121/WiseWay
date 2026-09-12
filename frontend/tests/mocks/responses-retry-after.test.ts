// E02-F7-REPAIR: контрактный `Retry-After` для управляемых mock-ответов 429.
//
// OAS `components.responses.RateLimited` требует заголовок `Retry-After`
// (`components.headers.RetryAfter`): `required: true`, `type: string`,
// `pattern: ^[0-9]+$`, первая версия — delta-seconds. Mock добавляет его в
// едином общем пути построения ответов (`responses.ts`), поэтому заголовок
// получает каждый управляемый 429 независимо от handler'а, а прочие статусы —
// нет.

import { describe, expect, it } from 'vitest'

import {
  errorResponse,
  exampleErrorResponse,
  jsonResponse,
  noContentResponse,
  notFoundResponse,
  RETRY_AFTER_HEADER,
  RETRY_AFTER_SECONDS,
} from '@/mocks/responses'
import type { ErrorResponse } from '@/mocks/types'

const REQUEST_ID = 'mock-request-retry-after'

describe('mock responses: Retry-After для 429', () => {
  it('exampleErrorResponse 429 отдаёт контрактный delta-seconds Retry-After', async () => {
    const response = exampleErrorResponse(REQUEST_ID, 'error-rate-limited', 429)

    expect(response.status).toBe(429)
    const retryAfter = response.headers.get(RETRY_AFTER_HEADER)
    expect(retryAfter).toBe(RETRY_AFTER_SECONDS)
    expect(retryAfter).toMatch(/^[0-9]+$/)

    const body = (await response.json()) as ErrorResponse
    expect(body.error.code).toBe('RATE_LIMITED')

    // Прочие контрактные заголовки не изменились.
    expect(response.headers.get('X-Request-ID')).toBe(REQUEST_ID)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(response.headers.get('X-WiseWay-Mock')).toBe('mock')
    expect(response.headers.get('Content-Type')).toBe('application/json')
  })

  it('errorResponse 429 тоже получает Retry-After', () => {
    const response = errorResponse(REQUEST_ID, 429, {
      code: 'RATE_LIMITED',
      message: 'Слишком много запросов.',
      retryable: true,
    })

    expect(response.status).toBe(429)
    expect(response.headers.get(RETRY_AFTER_HEADER)).toBe(RETRY_AFTER_SECONDS)
  })

  it.each([200, 201, 202, 400, 401, 403, 409, 422, 500, 503])(
    'jsonResponse со статусом %i не получает Retry-After',
    (status) => {
      const response = jsonResponse({ ok: false }, REQUEST_ID, status)

      expect(response.status).toBe(status)
      expect(response.headers.get(RETRY_AFTER_HEADER)).toBeNull()
    },
  )

  it('notFoundResponse 404 не получает Retry-After', () => {
    const response = notFoundResponse(REQUEST_ID)

    expect(response.status).toBe(404)
    expect(response.headers.get(RETRY_AFTER_HEADER)).toBeNull()
  })

  it('noContentResponse 204 не получает Retry-After', () => {
    const response = noContentResponse(REQUEST_ID)

    expect(response.status).toBe(204)
    expect(response.headers.get(RETRY_AFTER_HEADER)).toBeNull()
  })
})
