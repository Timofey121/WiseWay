import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getCsrfToken,
  onUnauthorized,
  resetSessionContext,
  setCsrfToken,
} from '@/api/session-context'
import {
  createApiClient,
  type WiseWayApiClient,
} from '@/api/transport'
import {
  isTransportError,
  throwIfError,
  toTransportError,
  TransportError,
  type FieldError,
} from '@/api/transport-error'

// Runtime-проверки единой безопасной модели ошибок транспорта. `fetch`
// подменён записывающим стабом: тесты проверяют фактические `TransportError`
// для всех объявленных статусов/кодов и сетевого сбоя, а также отсутствие
// утечки тел/секретов и ложного success.

const CSRF_TOKEN = 'session-csrf-token-1'
const REQUEST_ID = 'request-transport-error-1'
const OPERATION_ID = 'return-operation-demo-1'
const SECRET_PASSWORD = 'synthetic-password-should-not-leak'
const SECRET_QUERY = 'atlas-secret-query-should-not-leak'

interface ErrorDetailsInput {
  code: string
  message: string
  request_id: string
  operation_id: string | null
  retryable: boolean
  field_errors: FieldError[]
}

function errorBody(
  code: string,
  overrides: Partial<ErrorDetailsInput> = {},
): { error: ErrorDetailsInput } {
  return {
    error: {
      code,
      message: `Безопасное сообщение ${code}`,
      request_id: REQUEST_ID,
      operation_id: null,
      retryable: false,
      field_errors: [],
      ...overrides,
    },
  }
}

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': REQUEST_ID,
      ...headers,
    },
  })
}

function emptyResponse(
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(null, {
    status,
    headers: { 'X-Request-ID': REQUEST_ID, ...headers },
  })
}

function setup(
  respond: (request: Request) => Response | Promise<Response>,
): { api: WiseWayApiClient; requests: Request[] } {
  const requests: Request[] = []
  const fetchStub = vi.fn(async (input: Request): Promise<Response> => {
    requests.push(input)
    return respond(input)
  })
  const api = createApiClient({
    mode: 'real',
    baseUrl: 'http://localhost/api/v1',
    fetch: fetchStub,
  })
  return { api, requests }
}

const callHealth = (api: WiseWayApiClient) => api.GET('/health')

const callLogout = (api: WiseWayApiClient) =>
  api.POST('/auth/logout', {
    params: { header: { 'X-CSRF-Token': CSRF_TOKEN } },
  })

const callLogin = (api: WiseWayApiClient) =>
  api.POST('/auth/login', {
    body: { login: 'worker-atlas', password: SECRET_PASSWORD },
  })

/** Прогоняет операцию и возвращает безопасную `TransportError`. */
async function captureError(run: () => Promise<unknown>): Promise<TransportError> {
  try {
    await run()
  } catch (error) {
    return toTransportError(error)
  }
  throw new Error('Ожидалась ошибка транспорта, но запрос завершился успешно')
}

/** Прогоняет ошибку через `throwIfError`, как это делает вызывающий код. */
async function captureWithThrowIfError(
  result: Promise<unknown>,
): Promise<TransportError> {
  try {
    throwIfError((await result) as { response?: Response })
  } catch (error) {
    return toTransportError(error)
  }
  throw new Error('Ожидалась ошибка транспорта, но запрос завершился успешно')
}

beforeEach(() => {
  resetSessionContext()
})

describe('success не превращается в ошибку', () => {
  it('200 возвращает data без throw', async () => {
    const { api } = setup(() => jsonResponse(200, { status: 'ok' }))

    const data = throwIfError(await callHealth(api))

    expect(data).toEqual({ status: 'ok' })
  })

  it('204 возвращает undefined без throw', async () => {
    const { api, requests } = setup(() => emptyResponse(204))

    const data = throwIfError(await callLogout(api))

    expect(data).toBeUndefined()
    expect(requests).toHaveLength(1)
  })
})

describe('401: UNAUTHENTICATED очищает сессию, LOGIN_FAILED — нет', () => {
  it('UNAUTHENTICATED: сигнал очистки + TransportError', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    setCsrfToken(CSRF_TOKEN)
    const { api } = setup(() =>
      jsonResponse(
        401,
        errorBody('UNAUTHENTICATED', {
          message: 'Сессия отсутствует или истекла. Войдите снова.',
        }),
      ),
    )

    const error = await captureWithThrowIfError(callHealth(api))

    expect(isTransportError(error)).toBe(true)
    expect(error).toBeInstanceOf(TransportError)
    expect(error.kind).toBe('http')
    expect(error.status).toBe(401)
    expect(error.code).toBe('UNAUTHENTICATED')
    expect(error.message).toBe('Сессия отсутствует или истекла. Войдите снова.')
    expect(error.requestId).toBe(REQUEST_ID)
    expect(error.operationId).toBeNull()
    expect(error.retryable).toBe(false)
    expect(error.fieldErrors).toEqual([])
    expect(error.retryAfterSeconds).toBeNull()
    expect(listener).toHaveBeenCalledTimes(1)
    expect(getCsrfToken()).toBeNull()
    off()
  })

  it('LOGIN_FAILED: НЕТ сигнала очистки, форма-ошибка сохранена', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    setCsrfToken(CSRF_TOKEN)
    const { api } = setup(() =>
      jsonResponse(
        401,
        errorBody('LOGIN_FAILED', {
          message: 'Неверный логин или пароль.',
        }),
      ),
    )

    const error = await captureWithThrowIfError(callLogin(api))

    expect(error.code).toBe('LOGIN_FAILED')
    expect(error.status).toBe(401)
    expect(error.message).toBe('Неверный логин или пароль.')
    expect(listener).not.toHaveBeenCalled()
    expect(getCsrfToken()).toBe(CSRF_TOKEN)
    off()
  })

  it('нечитаемый 401 не очищает сессию (код не подтверждён)', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    setCsrfToken(CSRF_TOKEN)
    const { api } = setup(() =>
      new Response('<html>Unauthorized</html>', {
        status: 401,
        headers: { 'Content-Type': 'text/html', 'X-Request-ID': REQUEST_ID },
      }),
    )

    const error = await captureWithThrowIfError(callHealth(api))

    expect(error.code).toBe('UNAUTHENTICATED')
    expect(error.message).not.toContain('Unauthorized')
    expect(listener).not.toHaveBeenCalled()
    expect(getCsrfToken()).toBe(CSRF_TOKEN)
    off()
  })
})

describe('403: без auto-retry, без очистки, retryable=false', () => {
  for (const code of ['FORBIDDEN', 'CSRF_FAILED'] as const) {
    it(`${code}: один запрос и retryable=false`, async () => {
      const listener = vi.fn()
      const off = onUnauthorized(listener)
      setCsrfToken(CSRF_TOKEN)
      const { api, requests } = setup(() => jsonResponse(403, errorBody(code)))

      const error = await captureWithThrowIfError(callLogout(api))

      expect(error.status).toBe(403)
      expect(error.code).toBe(code)
      expect(error.retryable).toBe(false)
      expect(requests).toHaveLength(1)
      expect(listener).not.toHaveBeenCalled()
      expect(getCsrfToken()).toBe(CSRF_TOKEN)
      off()
    })
  }
})

describe('HTTP-статусы и коды по API §11', () => {
  const cases: {
    name: string
    status: number
    body: { error: ErrorDetailsInput }
    headers?: Record<string, string>
    code: string
    retryable: boolean
    retryAfterSeconds?: number | null
    fieldErrors?: FieldError[]
    operationId?: string | null
  }[] = [
    {
      name: '404 NOT_FOUND',
      status: 404,
      body: errorBody('NOT_FOUND', { message: 'Объект не найден.' }),
      code: 'NOT_FOUND',
      retryable: false,
    },
    {
      name: '409 STALE_PREVIEW',
      status: 409,
      body: errorBody('STALE_PREVIEW', {
        message: 'Данные изменились. Выполните проверку повторно.',
      }),
      code: 'STALE_PREVIEW',
      retryable: false,
    },
    {
      name: '409 DRAFT_VERSION_CONFLICT',
      status: 409,
      body: errorBody('DRAFT_VERSION_CONFLICT'),
      code: 'DRAFT_VERSION_CONFLICT',
      retryable: false,
    },
    {
      name: '422 VALIDATION_ERROR с field_errors',
      status: 422,
      body: errorBody('VALIDATION_ERROR', {
        field_errors: [
          {
            field: 'query_text',
            code: 'MAX_LENGTH',
            message: 'Допустимо не более 512 символов.',
          },
        ],
      }),
      code: 'VALIDATION_ERROR',
      retryable: false,
      fieldErrors: [
        {
          field: 'query_text',
          code: 'MAX_LENGTH',
          message: 'Допустимо не более 512 символов.',
        },
      ],
    },
    {
      name: '429 RATE_LIMITED с Retry-After',
      status: 429,
      body: errorBody('RATE_LIMITED', {
        message: 'Слишком много запросов. Повторите позже.',
        retryable: true,
      }),
      headers: { 'Retry-After': '30' },
      code: 'RATE_LIMITED',
      retryable: true,
      retryAfterSeconds: 30,
    },
    {
      name: '500 INTERNAL_ERROR',
      status: 500,
      body: errorBody('INTERNAL_ERROR'),
      code: 'INTERNAL_ERROR',
      retryable: false,
    },
    {
      name: '503 SERVICE_UNAVAILABLE',
      status: 503,
      body: errorBody('SERVICE_UNAVAILABLE', { retryable: true }),
      code: 'SERVICE_UNAVAILABLE',
      retryable: true,
    },
    {
      name: '503 SEARCH_UNAVAILABLE',
      status: 503,
      body: errorBody('SEARCH_UNAVAILABLE', { retryable: true }),
      code: 'SEARCH_UNAVAILABLE',
      retryable: true,
    },
    {
      name: '409 RECOVERY_REQUIRED с operation_id',
      status: 409,
      body: errorBody('RECOVERY_REQUIRED', {
        operation_id: OPERATION_ID,
      }),
      code: 'RECOVERY_REQUIRED',
      retryable: false,
      operationId: OPERATION_ID,
    },
  ]

  for (const testCase of cases) {
    it(testCase.name, async () => {
      const { api } = setup(() =>
        jsonResponse(testCase.status, testCase.body, testCase.headers),
      )

      const error = await captureWithThrowIfError(callHealth(api))

      expect(error.kind).toBe('http')
      expect(error.status).toBe(testCase.status)
      expect(error.code).toBe(testCase.code)
      expect(error.retryable).toBe(testCase.retryable)
      expect(error.requestId).toBe(REQUEST_ID)
      expect(error.operationId).toBe(testCase.operationId ?? null)
      expect(error.fieldErrors).toEqual(testCase.fieldErrors ?? [])
      expect(error.retryAfterSeconds).toBe(testCase.retryAfterSeconds ?? null)
    })
  }

  it('429 без тела: retryable=true по таблице §11', async () => {
    const { api } = setup(() => emptyResponse(429))

    const error = await captureWithThrowIfError(callHealth(api))

    expect(error.code).toBe('RATE_LIMITED')
    expect(error.retryable).toBe(true)
    expect(error.retryAfterSeconds).toBeNull()
  })
})

describe('синтез безопасного кода при отсутствии/битом теле', () => {
  const statusToCode: [number, string][] = [
    [401, 'UNAUTHENTICATED'],
    [403, 'FORBIDDEN'],
    [404, 'NOT_FOUND'],
    [409, 'INVALID_STATE'],
    [422, 'VALIDATION_ERROR'],
    [429, 'RATE_LIMITED'],
    [500, 'INTERNAL_ERROR'],
    [503, 'SERVICE_UNAVAILABLE'],
  ]

  for (const [status, code] of statusToCode) {
    it(`${status} без тела → ${code} с безопасным сообщением`, async () => {
      const { api } = setup(() => emptyResponse(status))

      const error = await captureWithThrowIfError(callHealth(api))

      expect(error.code).toBe(code)
      expect(error.message.length).toBeGreaterThan(0)
      expect(error.message).not.toContain('<')
      expect(error.requestId).toBe(REQUEST_ID)
    })
  }

  it('500 с битым JSON: INTERNAL_ERROR, request_id из заголовка', async () => {
    const { api } = setup(
      () =>
        new Response('not-json:{stack:at /srv/app}', {
          status: 500,
          headers: { 'Content-Type': 'text/plain', 'X-Request-ID': REQUEST_ID },
        }),
    )

    const error = await captureWithThrowIfError(callHealth(api))

    expect(error.code).toBe('INTERNAL_ERROR')
    expect(error.requestId).toBe(REQUEST_ID)
    expect(error.message).not.toContain('/srv/app')
    expect(error.message).not.toContain('not-json')
  })

  it('500 без тела: безопасное русское сообщение и request_id', async () => {
    const { api } = setup(() => emptyResponse(500))

    const error = await captureWithThrowIfError(callHealth(api))

    expect(error.code).toBe('INTERNAL_ERROR')
    expect(error.message).toBe(
      'Не удалось выполнить запрос. Сохраните идентификатор запроса для разбора.',
    )
    expect(error.requestId).toBe(REQUEST_ID)
    expect(error.retryable).toBe(false)
  })

  it('422 с чужим телом: VALIDATION_ERROR без чтения посторонних полей', async () => {
    const { api } = setup(() =>
      jsonResponse(422, { password: SECRET_PASSWORD, query_text: SECRET_QUERY }),
    )

    const error = await captureWithThrowIfError(callHealth(api))

    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.fieldErrors).toEqual([])
    expect(error.message).not.toContain(SECRET_PASSWORD)
    expect(error.message).not.toContain(SECRET_QUERY)
  })
})

describe('сетевой сбой', () => {
  it('fetch reject → kind network, NETWORK_ERROR, retryable, без ложного success', async () => {
    const networkFailure = new Error(
      `connect ECONNREFUSED http://localhost/api/v1/health?q=${SECRET_QUERY}`,
    )
    const { api } = setup(() => Promise.reject(networkFailure))

    const error = await captureWithThrowIfError(callHealth(api))

    expect(isTransportError(error)).toBe(true)
    expect(error.kind).toBe('network')
    expect(error.status).toBeNull()
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.retryable).toBe(true)
    expect(error.requestId).toBeNull()
    expect(error.operationId).toBeNull()
    expect(error.fieldErrors).toEqual([])
    expect(error.retryAfterSeconds).toBeNull()
    expect(error.message).not.toContain('ECONNREFUSED')
    expect(error.message).not.toContain(SECRET_QUERY)
  })

  it('timeout (AbortError) тоже безопасный network-сбой', async () => {
    const abortError = new DOMException('The operation was aborted.', 'AbortError')
    const { api } = setup(() => Promise.reject(abortError))

    const error = await captureError(async () => {
      throwIfError(await callHealth(api))
    })

    expect(error.kind).toBe('network')
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.message).not.toContain('aborted')
  })
})

describe('отсутствие утечки тела запроса/секретов', () => {
  it('валидная ошибка с эхом секретов на верхнем уровне не утекает', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    setCsrfToken(CSRF_TOKEN)
    const { api } = setup(() =>
      jsonResponse(401, {
        ...errorBody('LOGIN_FAILED', { message: 'Неверный логин или пароль.' }),
        password: SECRET_PASSWORD,
        query_text: SECRET_QUERY,
        request_body: { password: SECRET_PASSWORD, query_text: SECRET_QUERY },
      }),
    )

    const error = await captureWithThrowIfError(callLogin(api))

    const serialized = JSON.stringify(error)
    expect(error.message).not.toContain(SECRET_PASSWORD)
    expect(error.message).not.toContain(SECRET_QUERY)
    expect(serialized).not.toContain(SECRET_PASSWORD)
    expect(serialized).not.toContain(SECRET_QUERY)
    expect(error.fieldErrors).toEqual([])
    off()
  })

  it('битое тело с секретом не попадает в сообщение', async () => {
    const { api } = setup(
      () =>
        new Response(`500: password=${SECRET_PASSWORD} query=${SECRET_QUERY}`, {
          status: 500,
          headers: { 'X-Request-ID': REQUEST_ID },
        }),
    )

    const error = await captureWithThrowIfError(callLogin(api))

    expect(error.code).toBe('INTERNAL_ERROR')
    expect(error.message).not.toContain(SECRET_PASSWORD)
    expect(error.message).not.toContain(SECRET_QUERY)
    expect(JSON.stringify(error)).not.toContain(SECRET_PASSWORD)
  })
})

describe('toTransportError и isTransportError', () => {
  it('уже готовая TransportError возвращается без изменений', () => {
    const original = new TransportError({
      kind: 'http',
      status: 404,
      code: 'NOT_FOUND',
      message: 'Объект не найден.',
      requestId: REQUEST_ID,
      operationId: null,
      retryable: false,
      fieldErrors: [],
      retryAfterSeconds: null,
    })

    expect(toTransportError(original)).toBe(original)
  })

  it('isTransportError различает TransportError и обычный Error', () => {
    const transport = toTransportError(new Error('boom'))

    expect(isTransportError(transport)).toBe(true)
    expect(isTransportError(new Error('boom'))).toBe(false)
    expect(isTransportError(null)).toBe(false)
  })

  it('неизвестное значение трактуется как сетевой сбой', () => {
    const error = toTransportError(undefined)

    expect(error.kind).toBe('network')
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.retryable).toBe(true)
  })
})
