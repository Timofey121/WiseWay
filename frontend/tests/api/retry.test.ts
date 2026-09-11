import { beforeEach, describe, expect, it, vi } from 'vitest'

import { operationMeta } from '@/api/generated/operation-meta'
import {
  computeRetryDelay,
  createPollRegistry,
  createRetryFetch,
  defaultPollRegistry,
  defaultRetryConfig,
  getRequestOperationMeta,
  setRequestOperationMeta,
  shouldRetry,
  type RetryConfig,
  type RetryOperationMeta,
} from '@/api/retry'
import {
  clearSession,
  emitUnauthorized,
  resetSessionContext,
} from '@/api/session-context'
import { toTransportError, type TransportError } from '@/api/transport-error'
import {
  createApiClient,
  type CreateApiClientOptions,
  type WiseWayApiClient,
} from '@/api/transport'

// Проверки retry/backoff policy (API §2/§11, SEM «Повторы», TZ §12).
// Тесты используют controlled clocks: `sleep` записывает задержки и никогда
// реально не ждёт, `now` детерминирован. Никаких реальных `setTimeout`.

const CSRF = 'synthetic-csrf-token-1'
const IDEMPOTENCY_PLACEHOLDER = 'caller-placeholder-not-used'

interface RecordedRequest {
  method: string
  pathname: string
  headers: Headers
  body: unknown
}

type Responder = () => Response | Promise<Response>

function okResponse(body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(
  status: number,
  code: string,
  retryable: boolean,
  headers: Record<string, string> = {},
): Response {
  return new Response(
    JSON.stringify({
      error: {
        code,
        message: `Безопасное сообщение ${code}`,
        request_id: 'request-retry-1',
        operation_id: null,
        retryable,
        field_errors: [],
      },
    }),
    {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    },
  )
}

function opMeta(key: keyof typeof operationMeta): RetryOperationMeta {
  return {
    ...operationMeta[key],
    method: key.slice(0, key.indexOf(' ')),
  }
}

function httpError(
  status: number,
  headers: Record<string, string> = {},
): TransportError {
  return toTransportError(new Response(null, { status, headers }))
}

function networkError(): TransportError {
  return toTransportError(new TypeError('network down'))
}

interface SetupResult {
  api: WiseWayApiClient
  requests: RecordedRequest[]
  sleeps: number[]
  fetchStub: ReturnType<typeof vi.fn>
}

interface SetupOptions {
  responders?: Responder[]
  retry?: Partial<RetryConfig>
}

function setup(options: SetupOptions = {}): SetupResult {
  const requests: RecordedRequest[] = []
  const sleeps: number[] = []
  const responders = [...(options.responders ?? [])]
  const fetchStub = vi.fn(async (input: Request): Promise<Response> => {
    const rawBody = await input.clone().text()
    const url = new URL(input.url)
    requests.push({
      method: input.method,
      pathname: url.pathname,
      headers: new Headers(input.headers),
      body: rawBody === '' ? undefined : JSON.parse(rawBody),
    })
    const responder = responders.shift()
    return responder ? responder() : okResponse()
  })

  const clientOptions: CreateApiClientOptions = {
    mode: 'real',
    baseUrl: 'http://localhost/api/v1',
    fetch: fetchStub,
    sleep: async (milliseconds) => {
      sleeps.push(milliseconds)
    },
    now: () => 1_000_000,
    retry: options.retry,
  }

  return { api: createApiClient(clientOptions), requests, sleeps, fetchStub }
}

const searchBody = () => ({
  request_state_id: 'state-1',
  root_id: 'root-1',
  schema_set_version: 'schema-1',
  selected_marker_ids: [],
  query_text: 'atlas',
  sort: { field: 'RELEVANCE' as const, direction: 'DESC' as const },
  facet_prefix: '',
})

const callSearch = (api: WiseWayApiClient) =>
  api.POST('/search', { body: searchBody() })

const callGetSortingBatch = (api: WiseWayApiClient) =>
  api.GET('/sorting/batches/{batch_id}', {
    params: { path: { batch_id: 'batch-1' } },
  })

const callGetHealth = (api: WiseWayApiClient) => api.GET('/health')

const callLogin = (api: WiseWayApiClient) =>
  api.POST('/auth/login', {
    body: { login: 'worker-atlas', password: 'synthetic-password' },
  })

const callLogout = (api: WiseWayApiClient) =>
  api.POST('/auth/logout', {
    params: { header: { 'X-CSRF-Token': CSRF } },
  })

const callCreateDictionary = (api: WiseWayApiClient) =>
  api.POST('/companies/{company_id}/dictionaries', {
    params: {
      path: { company_id: 'company-1' },
      header: { 'X-CSRF-Token': CSRF },
    },
    body: { name: 'Справочник', description: 'Описание' },
  })

const callReplaceDictionaryDraft = (api: WiseWayApiClient) =>
  api.PUT('/dictionaries/{dictionary_id}/draft', {
    params: {
      path: { dictionary_id: 'dictionary-1' },
      header: { 'X-CSRF-Token': CSRF },
    },
    body: {
      expected_draft_revision: 0,
      name: 'Справочник',
      description: 'Описание',
      rules: [],
    },
  })

const callCreateSortingBatch = (api: WiseWayApiClient) =>
  api.POST('/sorting/batches', {
    params: {
      header: {
        'X-CSRF-Token': CSRF,
        'Idempotency-Key': IDEMPOTENCY_PLACEHOLDER,
      },
    },
    body: { selection_id: 'selection-1', execution_mode: 'DIRECT' as const },
  })

const NON_RETRYABLE_MUTATIONS: {
  operationId: string
  run: (api: WiseWayApiClient) => Promise<unknown>
}[] = [
  { operationId: 'login', run: callLogin },
  { operationId: 'logout', run: callLogout },
  { operationId: 'createDictionary', run: callCreateDictionary },
  { operationId: 'replaceDictionaryDraft', run: callReplaceDictionaryDraft },
]

beforeEach(() => {
  resetSessionContext()
})

// --- Чистые решения политики ------------------------------------------------

describe('shouldRetry: только разрешённые операции', () => {
  const retryable = httpError(503)

  it('безопасные чтения повторяются', () => {
    expect(shouldRetry(retryable, opMeta('GET /health'))).toBe(true)
    expect(shouldRetry(retryable, opMeta('GET /sorting/batches/{batch_id}'))).toBe(
      true,
    )
    expect(shouldRetry(retryable, opMeta('POST /search'))).toBe(true)
    expect(shouldRetry(retryable, opMeta('POST /search/facet'))).toBe(true)
    expect(shouldRetry(retryable, opMeta('POST /sorting/queue/query'))).toBe(true)
    expect(shouldRetry(retryable, opMeta('POST /audit/query'))).toBe(true)
  })

  it('три идемпотентные операции повторяются', () => {
    expect(
      shouldRetry(retryable, opMeta('POST /dictionaries/{dictionary_id}/publish')),
    ).toBe(true)
    expect(shouldRetry(retryable, opMeta('POST /sorting/batches'))).toBe(true)
    expect(
      shouldRetry(
        retryable,
        opMeta('POST /quarantine/{quarantine_id}/return'),
      ),
    ).toBe(true)
  })

  it('неидемпотентные мутации и login никогда не повторяются', () => {
    expect(
      shouldRetry(
        retryable,
        opMeta('POST /companies/{company_id}/dictionaries'),
      ),
    ).toBe(false)
    expect(
      shouldRetry(retryable, opMeta('PUT /dictionaries/{dictionary_id}/draft')),
    ).toBe(false)
    expect(
      shouldRetry(
        retryable,
        opMeta('POST /dictionaries/{dictionary_id}/restore-draft'),
      ),
    ).toBe(false)
    expect(
      shouldRetry(
        retryable,
        opMeta('POST /dictionaries/{dictionary_id}/simulate'),
      ),
    ).toBe(false)
    expect(shouldRetry(retryable, opMeta('POST /sorting/selections'))).toBe(false)
    expect(shouldRetry(retryable, opMeta('POST /sorting/previews'))).toBe(false)
    expect(shouldRetry(retryable, opMeta('POST /auth/logout'))).toBe(false)
    expect(shouldRetry(retryable, opMeta('POST /auth/login'))).toBe(false)
  })

  it('не-retryable ошибка и отсутствие metadata запрещают повтор', () => {
    expect(shouldRetry(httpError(422), opMeta('GET /health'))).toBe(false)
    expect(shouldRetry(retryable, undefined)).toBe(false)
  })
})

describe('computeRetryDelay: Retry-After и backoff', () => {
  const config: RetryConfig = {
    maxAttempts: 3,
    baseDelayMs: 500,
    maxDelayMs: 8000,
    jitter: false,
  }

  it('Retry-After (delta-seconds) имеет приоритет', () => {
    const error = httpError(429, { 'Retry-After': '3' })
    expect(computeRetryDelay(error, 0, config)).toBe(3000)
  })

  it('Retry-After ограничивается сверху maxDelayMs', () => {
    const error = httpError(429, { 'Retry-After': '120' })
    expect(computeRetryDelay(error, 0, config)).toBe(8000)
  })

  it('без Retry-After — экспоненциальный backoff с cap', () => {
    const error = httpError(503)
    expect(computeRetryDelay(error, 0, config)).toBe(500)
    expect(computeRetryDelay(error, 1, config)).toBe(1000)
    expect(computeRetryDelay(error, 2, config)).toBe(2000)
    expect(computeRetryDelay(error, 3, config)).toBe(4000)
    expect(computeRetryDelay(error, 4, config)).toBe(8000)
    expect(computeRetryDelay(error, 10, config)).toBe(8000)
  })

  it('сетевой сбой тоже даёт экспоненциальный backoff', () => {
    expect(computeRetryDelay(networkError(), 0, config)).toBe(500)
  })

  it('jitter уменьшает задержку, не превышая cap', () => {
    const randomSpy = vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const jitterConfig: RetryConfig = { ...config, jitter: true }
    expect(computeRetryDelay(httpError(503), 2, jitterConfig)).toBe(1000)
    randomSpy.mockRestore()
  })
})

// --- createRetryFetch напрямую ----------------------------------------------

describe('createRetryFetch: тот же Request при повторе', () => {
  it('повторяет сетевой сбой и возвращает успешный ответ', async () => {
    const baseFetch = vi
      .fn<(input: Request, init?: RequestInit) => Promise<Response>>()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(okResponse())
    const sleeps: number[] = []
    const retryFetch = createRetryFetch(baseFetch, {
      config: { maxAttempts: 3, baseDelayMs: 10, maxDelayMs: 100, jitter: false },
      sleep: async (ms) => {
        sleeps.push(ms)
      },
    })

    const request = new Request('http://localhost/api/v1/health', {
      method: 'GET',
    })
    setRequestOperationMeta(request, opMeta('GET /health'))

    const response = await retryFetch(request)

    expect(response.status).toBe(200)
    expect(baseFetch).toHaveBeenCalledTimes(2)
    expect(sleeps).toEqual([10])
  })

  it('без metadata не повторяет', async () => {
    const baseFetch = vi
      .fn<(input: Request, init?: RequestInit) => Promise<Response>>()
      .mockRejectedValueOnce(new TypeError('network down'))
    const retryFetch = createRetryFetch(baseFetch, {
      config: { maxAttempts: 3, jitter: false },
      sleep: async () => {},
    })

    await expect(
      retryFetch(new Request('http://localhost/api/v1/health')),
    ).rejects.toBeInstanceOf(TypeError)
    expect(baseFetch).toHaveBeenCalledTimes(1)
  })

  it('maxAttempts=1 не повторяет даже разрешённое чтение', async () => {
    const baseFetch = vi
      .fn<(input: Request, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(errorResponse(503, 'SERVICE_UNAVAILABLE', true))
    const retryFetch = createRetryFetch(baseFetch, {
      config: { maxAttempts: 1, jitter: false },
      sleep: async () => {},
    })

    const request = new Request('http://localhost/api/v1/health')
    setRequestOperationMeta(request, opMeta('GET /health'))

    const response = await retryFetch(request)

    expect(response.status).toBe(503)
    expect(baseFetch).toHaveBeenCalledTimes(1)
  })

  it('metadata хранится в WeakMap и не уходит в заголовки', () => {
    const request = new Request('http://localhost/api/v1/health')
    setRequestOperationMeta(request, opMeta('GET /health'))
    expect(getRequestOperationMeta(request)?.operationId).toBe('getHealth')
    expect(request.headers.get('operationId')).toBeNull()
    expect(getRequestOperationMeta(new Request('http://x/'))).toBeUndefined()
  })
})

// --- Интеграция с транспортом ------------------------------------------------

describe('транспорт: чтения повторяются', () => {
  it('429 c Retry-After: задержка N и повтор с тем же телом', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => errorResponse(429, 'RATE_LIMITED', true, { 'Retry-After': '3' }),
        () => okResponse({}),
      ],
    })

    const result = await callSearch(api)

    expect(result.response?.status).toBe(200)
    expect(requests).toHaveLength(2)
    expect(sleeps).toEqual([3000])
    expect(requests[1].body).toEqual(requests[0].body)
  })

  it('503 повторяется с экспоненциальным backoff', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => okResponse({}),
      ],
      retry: { maxAttempts: 3, baseDelayMs: 100, maxDelayMs: 1000, jitter: false },
    })

    const result = await callGetSortingBatch(api)

    expect(result.response?.status).toBe(200)
    expect(requests).toHaveLength(3)
    expect(sleeps).toEqual([100, 200])
  })

  it('сетевой сбой чтения повторяется', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => {
          throw new TypeError('network down')
        },
        () => okResponse({}),
      ],
      retry: { maxAttempts: 2, baseDelayMs: 50, jitter: false },
    })

    const result = await callGetHealth(api)

    expect(result.response?.status).toBe(200)
    expect(requests).toHaveLength(2)
    expect(sleeps).toEqual([50])
  })

  it('после исчерпания попыток ошибка не теряется (HTTP)', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
      ],
      retry: { maxAttempts: 3, baseDelayMs: 100, jitter: false },
    })

    const result = await callGetHealth(api)

    expect(result.error).toBeDefined()
    expect(result.response?.status).toBe(503)
    expect(requests).toHaveLength(3)
    expect(sleeps).toEqual([100, 200])
  })

  it('после исчерпания попыток сетевая ошибка пробрасывается', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => {
          throw new TypeError('network down')
        },
        () => {
          throw new TypeError('network down')
        },
      ],
      retry: { maxAttempts: 2, baseDelayMs: 50, jitter: false },
    })

    await expect(callGetHealth(api)).rejects.toBeInstanceOf(TypeError)
    expect(requests).toHaveLength(2)
    expect(sleeps).toEqual([50])
  })
})

describe('транспорт: неидемпотентные мутации не повторяются', () => {
  for (const { operationId, run } of NON_RETRYABLE_MUTATIONS) {
    it(`${operationId}: ровно один fetch при 503`, async () => {
      const { api, requests, sleeps } = setup({
        responders: [() => errorResponse(503, 'SERVICE_UNAVAILABLE', true)],
        retry: { maxAttempts: 3, baseDelayMs: 100, jitter: false },
      })

      await run(api)

      expect(requests).toHaveLength(1)
      expect(sleeps).toEqual([])
    })

    it(`${operationId}: ровно один fetch при сетевом сбое`, async () => {
      const { api, requests, sleeps } = setup({
        responders: [
          () => {
            throw new TypeError('network down')
          },
        ],
        retry: { maxAttempts: 3, baseDelayMs: 100, jitter: false },
      })

      await expect(run(api)).rejects.toBeInstanceOf(TypeError)
      expect(requests).toHaveLength(1)
      expect(sleeps).toEqual([])
    })
  }
})

describe('транспорт: идемпотентная операция повторяется с тем же ключом/телом', () => {
  it('createSortingBatch: 3 попытки, тот же Idempotency-Key и body', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => okResponse({ batch_id: 'batch-1' }),
      ],
      retry: { maxAttempts: 3, baseDelayMs: 100, maxDelayMs: 1000, jitter: false },
    })

    await callCreateSortingBatch(api)

    expect(requests).toHaveLength(3)
    expect(sleeps).toEqual([100, 200])

    const keys = requests.map((request) =>
      request.headers.get('Idempotency-Key'),
    )
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
    expect(keys[2]).toBe(keys[0])
    expect(requests[1].body).toEqual(requests[0].body)
    expect(requests[2].body).toEqual(requests[0].body)
  })

  it('createSortingBatch: сетевой сбой → повтор с тем же ключом/телом', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => {
          throw new TypeError('network down')
        },
        () => okResponse({ batch_id: 'batch-1' }),
      ],
      retry: { maxAttempts: 2, baseDelayMs: 50, jitter: false },
    })

    await callCreateSortingBatch(api)

    expect(requests).toHaveLength(2)
    expect(sleeps).toEqual([50])
    expect(requests[1].headers.get('Idempotency-Key')).toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
    expect(requests[1].body).toEqual(requests[0].body)
  })

  it('publishDictionary: 429 → повтор с тем же ключом/телом', async () => {
    const { api, requests, sleeps } = setup({
      responders: [
        () => errorResponse(429, 'RATE_LIMITED', true, { 'Retry-After': '2' }),
        () => okResponse({}),
      ],
    })

    await api.POST('/dictionaries/{dictionary_id}/publish', {
      params: {
        path: { dictionary_id: 'dictionary-1' },
        header: {
          'X-CSRF-Token': CSRF,
          'Idempotency-Key': IDEMPOTENCY_PLACEHOLDER,
        },
      },
      body: {
        expected_draft_revision: 0,
        simulation_id: 'simulation-1',
        acknowledge_no_scenario: false,
        comment: 'Комментарий',
      },
    })

    expect(requests).toHaveLength(2)
    expect(sleeps).toEqual([2000])
    expect(requests[1].headers.get('Idempotency-Key')).toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
    expect(requests[1].body).toEqual(requests[0].body)
  })
})

// --- Single-flight poll registry ---------------------------------------------

describe('createPollRegistry: нет одинаковых параллельных polls', () => {
  it('два run с одним ключом дают один базовый вызов и тот же promise', async () => {
    const registry = createPollRegistry()
    let resolve!: (value: string) => void
    const fn = vi.fn(
      () =>
        new Promise<string>((innerResolve) => {
          resolve = innerResolve
        }),
    )

    const first = registry.run('batch-1', fn)
    const second = registry.run('batch-1', fn)

    expect(fn).toHaveBeenCalledTimes(1)
    expect(second).toBe(first)
    expect(registry.has('batch-1')).toBe(true)

    resolve('done')
    await expect(first).resolves.toBe('done')
    await expect(second).resolves.toBe('done')
    expect(registry.has('batch-1')).toBe(false)
  })

  it('разные ключи не коалесцируются', async () => {
    const registry = createPollRegistry()
    const fn = vi.fn(async (value: string) => value)

    await Promise.all([
      registry.run('batch-1', () => fn('a')),
      registry.run('batch-2', () => fn('b')),
    ])

    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('после settle новый run запускает новый запрос', async () => {
    const registry = createPollRegistry()
    const fn = vi.fn(async () => 'value')

    await registry.run('audit', fn)
    await registry.run('audit', fn)

    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('ошибка снимает in-flight, следующий run работает', async () => {
    const registry = createPollRegistry()
    const failing = vi.fn(async () => {
      throw new Error('poll failed')
    })

    await expect(registry.run('audit', failing)).rejects.toThrow('poll failed')
    expect(registry.has('audit')).toBe(false)

    const ok = vi.fn(async () => 'ok')
    await expect(registry.run('audit', ok)).resolves.toBe('ok')
    expect(ok).toHaveBeenCalledTimes(1)
  })

  it('clear() сбрасывает состояние', async () => {
    const registry = createPollRegistry()
    const resolvers: ((value: string) => void)[] = []
    const fn = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolvers.push(resolve)
        }),
    )

    const first = registry.run('batch-1', fn)
    expect(registry.has('batch-1')).toBe(true)

    registry.clear()
    expect(registry.has('batch-1')).toBe(false)

    const second = registry.run('batch-1', fn)
    expect(fn).toHaveBeenCalledTimes(2)
    expect(second).not.toBe(first)

    resolvers[0]('first')
    resolvers[1]('second')
    await expect(first).resolves.toBe('first')
    await expect(second).resolves.toBe('second')
  })
})

describe('session cleanup очищает poll-состояние', () => {
  it('clearSession сбрасывает defaultPollRegistry', () => {
    let resolve!: (value: string) => void
    const pending = defaultPollRegistry.run(
      'audit',
      () =>
        new Promise<string>((innerResolve) => {
          resolve = innerResolve
        }),
    )

    expect(defaultPollRegistry.has('audit')).toBe(true)
    clearSession()
    expect(defaultPollRegistry.has('audit')).toBe(false)
    resolve('done')
    return pending
  })

  it('emitUnauthorized сбрасывает defaultPollRegistry', () => {
    let resolve!: (value: string) => void
    const pending = defaultPollRegistry.run(
      'batch-1',
      () =>
        new Promise<string>((innerResolve) => {
          resolve = innerResolve
        }),
    )

    expect(defaultPollRegistry.has('batch-1')).toBe(true)
    emitUnauthorized()
    expect(defaultPollRegistry.has('batch-1')).toBe(false)
    resolve('done')
    return pending
  })
})

describe('defaultRetryConfig', () => {
  it('ограничивает число попыток и задержку', () => {
    expect(defaultRetryConfig.maxAttempts).toBeGreaterThanOrEqual(1)
    expect(defaultRetryConfig.baseDelayMs).toBeGreaterThan(0)
    expect(defaultRetryConfig.maxDelayMs).toBeGreaterThanOrEqual(
      defaultRetryConfig.baseDelayMs,
    )
  })
})
