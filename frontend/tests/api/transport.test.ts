import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  operationMeta,
  type OperationMeta,
} from '@/api/generated/operation-meta'
import {
  clearSession,
  getCsrfToken,
  onUnauthorized,
  resetSessionContext,
  setCsrfToken,
} from '@/api/session-context'
import {
  createApiClient,
  type CreateApiClientOptions,
  type WiseWayApiClient,
} from '@/api/transport'

// Runtime-проверки состава `Request`, который формирует транспорт. `fetch`
// подменён записывающим стабом: тесты проверяют фактические
// method/path/credentials/cache/headers/body, а не поведение сети.

const CSRF_TOKEN = 'session-csrf-token-1'
const CALLER_CSRF = 'caller-csrf-placeholder'
const IDEMPOTENCY_KEY = 'idem-key-1'
const CALLER_IDEMPOTENCY = 'caller-idem-placeholder'
const REQUEST_ID = 'request-transport-test-1'

interface RecordedRequest {
  method: string
  pathname: string
  credentials: RequestCredentials
  cache: RequestCache
  headers: Headers
  body: unknown
}

function defaultOkResponse(): Response {
  return new Response('{}', {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': REQUEST_ID,
    },
  })
}

type SetupOptions = Partial<
  Pick<
    CreateApiClientOptions,
    'mode' | 'csrfTokenProvider' | 'idempotencyKeyProvider' | 'onRequestId'
  >
> & {
  response?: () => Response
}

function setup(options: SetupOptions = {}) {
  const requests: RecordedRequest[] = []
  const fetchStub = vi.fn(async (input: Request): Promise<Response> => {
    const rawBody = await input.clone().text()
    const url = new URL(input.url)
    requests.push({
      method: input.method,
      pathname: url.pathname,
      credentials: input.credentials,
      cache: input.cache,
      headers: input.headers,
      body: rawBody === '' ? undefined : JSON.parse(rawBody),
    })
    return options.response?.() ?? defaultOkResponse()
  })

  const api = createApiClient({
    mode: options.mode ?? 'real',
    baseUrl: 'http://localhost/api/v1',
    fetch: fetchStub,
    csrfTokenProvider: options.csrfTokenProvider,
    idempotencyKeyProvider: options.idempotencyKeyProvider,
    onRequestId: options.onRequestId,
  })

  return { api, requests, fetchStub }
}

function lastRequest(requests: RecordedRequest[]): RecordedRequest {
  const request = requests.at(-1)
  if (!request) {
    throw new Error('Транспорт не выполнил ни одного запроса')
  }
  return request
}

const callLogout = (api: WiseWayApiClient) =>
  api.POST('/auth/logout', {
    params: { header: { 'X-CSRF-Token': CALLER_CSRF } },
  })

const callCreateDictionary = (api: WiseWayApiClient) =>
  api.POST('/companies/{company_id}/dictionaries', {
    params: {
      path: { company_id: 'company-1' },
      header: { 'X-CSRF-Token': CALLER_CSRF },
    },
    body: { name: 'Справочник', description: 'Описание' },
  })

const callReplaceDictionaryDraft = (api: WiseWayApiClient) =>
  api.PUT('/dictionaries/{dictionary_id}/draft', {
    params: {
      path: { dictionary_id: 'dictionary-1' },
      header: { 'X-CSRF-Token': CALLER_CSRF },
    },
    body: {
      expected_draft_revision: 0,
      name: 'Справочник',
      description: 'Описание',
      rules: [],
    },
  })

const callRestoreDictionaryDraft = (api: WiseWayApiClient) =>
  api.POST('/dictionaries/{dictionary_id}/restore-draft', {
    params: {
      path: { dictionary_id: 'dictionary-1' },
      header: { 'X-CSRF-Token': CALLER_CSRF },
    },
    body: { version_id: 'version-1', expected_draft_revision: 0 },
  })

const callCreateDictionarySimulation = (api: WiseWayApiClient) =>
  api.POST('/dictionaries/{dictionary_id}/simulate', {
    params: {
      path: { dictionary_id: 'dictionary-1' },
      header: { 'X-CSRF-Token': CALLER_CSRF },
    },
    body: { expected_draft_revision: 0 },
  })

const callPublishDictionary = (api: WiseWayApiClient) =>
  api.POST('/dictionaries/{dictionary_id}/publish', {
    params: {
      path: { dictionary_id: 'dictionary-1' },
      header: {
        'X-CSRF-Token': CALLER_CSRF,
        'Idempotency-Key': CALLER_IDEMPOTENCY,
      },
    },
    body: {
      expected_draft_revision: 0,
      simulation_id: 'simulation-1',
      acknowledge_no_scenario: false,
      comment: 'Комментарий',
    },
  })

const callCreateSortingSelection = (api: WiseWayApiClient) =>
  api.POST('/sorting/selections', {
    params: { header: { 'X-CSRF-Token': CALLER_CSRF } },
    body: {
      company_id: 'company-1',
      mode: 'EXPLICIT',
      items: [{ item_id: 'item-1', item_revision: 1 }],
    },
  })

const callCreateSortingPreview = (api: WiseWayApiClient) =>
  api.POST('/sorting/previews', {
    params: { header: { 'X-CSRF-Token': CALLER_CSRF } },
    body: { selection_id: 'selection-1' },
  })

const callCreateSortingBatch = (api: WiseWayApiClient) =>
  api.POST('/sorting/batches', {
    params: {
      header: {
        'X-CSRF-Token': CALLER_CSRF,
        'Idempotency-Key': CALLER_IDEMPOTENCY,
      },
    },
    body: { selection_id: 'selection-1', execution_mode: 'DIRECT' },
  })

const callReturnQuarantineItem = (api: WiseWayApiClient) =>
  api.POST('/quarantine/{quarantine_id}/return', {
    params: {
      path: { quarantine_id: 'quarantine-1' },
      header: {
        'X-CSRF-Token': CALLER_CSRF,
        'Idempotency-Key': CALLER_IDEMPOTENCY,
      },
    },
    body: { expected_revision: 1, comment: 'Комментарий' },
  })

const CSRF_OPERATIONS: {
  operationId: string
  run: (api: WiseWayApiClient) => Promise<unknown>
}[] = [
  { operationId: 'logout', run: callLogout },
  { operationId: 'createDictionary', run: callCreateDictionary },
  { operationId: 'replaceDictionaryDraft', run: callReplaceDictionaryDraft },
  { operationId: 'restoreDictionaryDraft', run: callRestoreDictionaryDraft },
  {
    operationId: 'createDictionarySimulation',
    run: callCreateDictionarySimulation,
  },
  { operationId: 'publishDictionary', run: callPublishDictionary },
  { operationId: 'createSortingSelection', run: callCreateSortingSelection },
  { operationId: 'createSortingPreview', run: callCreateSortingPreview },
  { operationId: 'createSortingBatch', run: callCreateSortingBatch },
  { operationId: 'returnQuarantineItem', run: callReturnQuarantineItem },
]

const IDEMPOTENCY_OPERATIONS: {
  operationId: string
  run: (api: WiseWayApiClient) => Promise<unknown>
}[] = [
  { operationId: 'publishDictionary', run: callPublishDictionary },
  { operationId: 'createSortingBatch', run: callCreateSortingBatch },
  { operationId: 'returnQuarantineItem', run: callReturnQuarantineItem },
]

const READ_OPERATIONS: {
  operationId: string
  run: (api: WiseWayApiClient) => Promise<unknown>
}[] = [
  {
    operationId: 'getHealth',
    run: (api) => api.GET('/health', { headers: { 'X-CSRF-Token': CALLER_CSRF } }),
  },
  {
    operationId: 'getSession',
    run: (api) => api.GET('/session', { headers: { 'X-CSRF-Token': CALLER_CSRF } }),
  },
  {
    operationId: 'searchFiles',
    run: (api) =>
      api.POST('/search', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        body: {
          request_state_id: 'state-1',
          root_id: 'root-1',
          schema_set_version: 'schema-1',
          selected_marker_ids: [],
          query_text: 'atlas',
          sort: { field: 'RELEVANCE', direction: 'DESC' },
          facet_prefix: '',
        },
      }),
  },
  {
    operationId: 'getSearchFacet',
    run: (api) =>
      api.POST('/search/facet', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        body: {
          request_state_id: 'state-2',
          root_id: 'root-1',
          schema_set_version: 'schema-1',
          selected_marker_ids: [],
          query_text: 'atlas',
          facet_prefix: '',
        },
      }),
  },
  {
    operationId: 'querySortingQueue',
    run: (api) =>
      api.POST('/sorting/queue/query', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        body: {
          company_id: 'company-1',
          filters: { statuses: ['READY'], query_text: '' },
          cursor: null,
          limit: 50,
        },
      }),
  },
  {
    operationId: 'queryAuditEvents',
    run: (api) =>
      api.POST('/audit/query', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        body: {
          company_id: null,
          from: '2031-05-10T00:00:00Z',
          to: '2031-05-11T00:00:00Z',
          actor_id: null,
          action: null,
          result: null,
          query_text: '',
          cursor: null,
          limit: 100,
        },
      }),
  },
  {
    operationId: 'getAuditUpdates',
    run: (api) =>
      api.GET('/audit/updates', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        params: { query: { after_event_id: 'event-1' } },
      }),
  },
  {
    operationId: 'listAuditActors',
    run: (api) =>
      api.GET('/audit/actors', {
        headers: { 'X-CSRF-Token': CALLER_CSRF },
        params: { query: { prefix: 'work' } },
      }),
  },
]

beforeEach(() => {
  resetSessionContext()
})

describe('operation-meta из OAS', () => {
  it('покрывает все 33 операции', () => {
    expect(Object.keys(operationMeta)).toHaveLength(33)
  })

  it('csrf=true ровно у 10 объявленных мутаций', () => {
    const csrf = Object.entries(operationMeta)
      .filter(([, meta]) => meta.csrf)
      .map(([, meta]) => meta.operationId)
      .sort()

    expect(csrf).toEqual(
      [
        'logout',
        'createDictionary',
        'replaceDictionaryDraft',
        'restoreDictionaryDraft',
        'createDictionarySimulation',
        'publishDictionary',
        'createSortingSelection',
        'createSortingPreview',
        'createSortingBatch',
        'returnQuarantineItem',
      ].sort(),
    )
  })

  it('idempotencyKey=true ровно у 3 операций', () => {
    const idempotent = Object.entries(operationMeta)
      .filter(([, meta]) => meta.idempotencyKey)
      .map(([, meta]) => meta.operationId)
      .sort()

    expect(idempotent).toEqual(
      ['publishDictionary', 'createSortingBatch', 'returnQuarantineItem'].sort(),
    )
  })

  it('читающие POST не объявляют CSRF', () => {
    const readingPosts = [
      'searchFiles',
      'getSearchFacet',
      'querySortingQueue',
      'queryAuditEvents',
    ]
    for (const operationId of readingPosts) {
      const entry = Object.values(operationMeta).find(
        (meta: OperationMeta) => meta.operationId === operationId,
      )
      expect(entry, operationId).toBeDefined()
      expect(entry?.csrf, operationId).toBe(false)
    }
  })
})

describe('real-режим: cookie credentials и no-store', () => {
  it('GET идёт с credentials include и cache no-store', async () => {
    const { api, requests } = setup()
    await api.GET('/health')
    const request = lastRequest(requests)
    expect(request.credentials).toBe('include')
    expect(request.cache).toBe('no-store')
  })

  it('мутация идёт с credentials include и cache no-store', async () => {
    const { api, requests } = setup()
    setCsrfToken(CSRF_TOKEN)
    await callCreateDictionary(api)
    const request = lastRequest(requests)
    expect(request.credentials).toBe('include')
    expect(request.cache).toBe('no-store')
  })
})

describe('CSRF: только объявленные мутации', () => {
  for (const { operationId, run } of CSRF_OPERATIONS) {
    it(`${operationId}: ставит X-CSRF-Token из session-context`, async () => {
      const { api, requests } = setup()
      setCsrfToken(CSRF_TOKEN)

      await run(api)

      expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBe(CSRF_TOKEN)
    })
  }

  for (const { operationId, run } of READ_OPERATIONS) {
    it(`${operationId}: не несёт X-CSRF-Token`, async () => {
      const { api, requests } = setup()
      setCsrfToken(CSRF_TOKEN)

      await run(api)

      expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBeNull()
    })
  }

  it('csrfTokenProvider имеет приоритет над session-context', async () => {
    const { api, requests } = setup({
      csrfTokenProvider: () => 'provider-csrf-token',
    })
    setCsrfToken(CSRF_TOKEN)

    await callCreateDictionary(api)

    expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBe(
      'provider-csrf-token',
    )
  })

  it('CSRF lifecycle: set → header, смена → новое значение, clear → отсутствует', async () => {
    const { api, requests } = setup()

    setCsrfToken('token-1')
    await callLogout(api)
    expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBe('token-1')

    setCsrfToken('token-2')
    await callLogout(api)
    expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBe('token-2')

    clearSession()
    await callLogout(api)
    expect(lastRequest(requests).headers.get('X-CSRF-Token')).toBeNull()
    expect(getCsrfToken()).toBeNull()
  })
})

describe('Idempotency-Key: только предоставленный и только на 3 операциях', () => {
  for (const { operationId, run } of IDEMPOTENCY_OPERATIONS) {
    it(`${operationId}: ставит ключ провайдера`, async () => {
      const { api, requests } = setup({
        idempotencyKeyProvider: () => IDEMPOTENCY_KEY,
      })

      await run(api)

      expect(lastRequest(requests).headers.get('Idempotency-Key')).toBe(
        IDEMPOTENCY_KEY,
      )
    })
  }

  it('без провайдера Idempotency-Key отсутствует', async () => {
    const { api, requests } = setup()

    await callCreateSortingBatch(api)

    expect(lastRequest(requests).headers.get('Idempotency-Key')).toBeNull()
  })

  it('неидемпотентная мутация не получает Idempotency-Key', async () => {
    const idempotencyKeyProvider = vi.fn(() => IDEMPOTENCY_KEY)
    const { api, requests } = setup({ idempotencyKeyProvider })

    await callCreateDictionary(api)

    expect(lastRequest(requests).headers.get('Idempotency-Key')).toBeNull()
    expect(idempotencyKeyProvider).not.toHaveBeenCalled()
  })

  it('провайдер не вызывается для чтения', async () => {
    const idempotencyKeyProvider = vi.fn(() => IDEMPOTENCY_KEY)
    const { api } = setup({ idempotencyKeyProvider })

    await api.GET('/health')

    expect(idempotencyKeyProvider).not.toHaveBeenCalled()
  })
})

describe('безопасные ответы и ошибки', () => {
  it('X-Request-ID ответа доходит до onRequestId', async () => {
    const onRequestId = vi.fn()
    const { api } = setup({ onRequestId })

    await api.GET('/health')

    expect(onRequestId).toHaveBeenCalledWith(REQUEST_ID)
  })

  it('401 очищает сессию, уведомляет подписчика и остаётся ошибкой', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    const { api } = setup({
      response: () =>
        new Response(
          JSON.stringify({
            error: { code: 'UNAUTHENTICATED', message: 'Требуется вход' },
          }),
          {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
    })
    setCsrfToken(CSRF_TOKEN)

    const result = await api.GET('/session')

    expect(listener).toHaveBeenCalledTimes(1)
    expect(getCsrfToken()).toBeNull()
    expect(result.data).toBeUndefined()
    expect(result.error).toBeDefined()
    off()
  })

  it('403 не повторяет запрос автоматически и не сбрасывает сессию', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    const { api, requests } = setup({
      response: () =>
        new Response(
          JSON.stringify({
            error: { code: 'CSRF_FAILED', message: 'Запрос отклонён' },
          }),
          {
            status: 403,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
    })
    setCsrfToken(CSRF_TOKEN)

    await callCreateDictionary(api)

    expect(requests).toHaveLength(1)
    expect(listener).not.toHaveBeenCalled()
    expect(getCsrfToken()).toBe(CSRF_TOKEN)
    off()
  })
})

describe('mock-режим', () => {
  it('использует переданный fetch и не включает cookie credentials', async () => {
    const { api, requests } = setup({ mode: 'mock' })

    await api.GET('/health')

    const request = lastRequest(requests)
    expect(requests).toHaveLength(1)
    expect(request.pathname).toBe('/api/v1/health')
    expect(request.cache).toBe('no-store')
    expect(request.credentials).not.toBe('include')
  })

  it('без fetch-перехватчика бросает ошибку', () => {
    expect(() => createApiClient({ mode: 'mock' })).toThrow()
  })
})
