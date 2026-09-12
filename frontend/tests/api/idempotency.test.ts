import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createIdempotencyStore,
  fingerprintBody,
  type IdempotencyStore,
} from '@/api/idempotency'
import {
  clearSession,
  emitUnauthorized,
  resetSessionContext,
} from '@/api/session-context'
import {
  createApiClient,
  type CreateApiClientOptions,
  type WiseWayApiClient,
} from '@/api/transport'

// Runtime-проверки in-memory состояния идемпотентности (API §2, QUEUE-09).
// `fetch` подменён записывающим стабом: тесты проверяют фактический
// `Idempotency-Key`/тело, жизненный цикл ключа и session-scope очистку.

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const CSRF = 'synthetic-csrf-token-1'
// Тип generated-клиента требует заголовок `Idempotency-Key`; транспорт
// переопределяет его ключом из store, поэтому значение-заглушка не уходит.
const IDEMPOTENCY_PLACEHOLDER = 'caller-placeholder-not-used'

interface RecordedRequest {
  method: string
  pathname: string
  headers: Headers
  body: unknown
}

type RunOperation = (api: WiseWayApiClient) => Promise<unknown>
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
        request_id: 'request-idempotency-1',
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

interface SetupOptions {
  store?: IdempotencyStore
  responders?: Responder[]
  defaultStore?: boolean
}

function setup(options: SetupOptions = {}): {
  api: WiseWayApiClient
  requests: RecordedRequest[]
  store: IdempotencyStore
} {
  const requests: RecordedRequest[] = []
  const responders = [...(options.responders ?? [])]
  const store = options.store ?? createIdempotencyStore()
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
    // Этот suite проверяет жизненный цикл Idempotency-Key, а не retry-policy:
    // повторы отключены, чтобы 429/503/сеть проверяли именно retain/complete.
    retry: { maxAttempts: 1 },
    sleep: async () => {},
  }
  if (!options.defaultStore) {
    clientOptions.idempotencyStore = store
  }

  return { api: createApiClient(clientOptions), requests, store }
}

function lastRequest(requests: RecordedRequest[]): RecordedRequest {
  const request = requests.at(-1)
  if (!request) {
    throw new Error('Транспорт не выполнил ни одного запроса')
  }
  return request
}

// --- Тела и вызовы операций ------------------------------------------------

function publishBody(comment = 'Комментарий'): {
  expected_draft_revision: number
  simulation_id: string
  acknowledge_no_scenario: boolean
  comment: string
} {
  return {
    expected_draft_revision: 0,
    simulation_id: 'simulation-1',
    acknowledge_no_scenario: false,
    comment,
  }
}

function batchBody(selectionId = 'selection-1'): {
  selection_id: string
  execution_mode: 'DIRECT'
} {
  return { selection_id: selectionId, execution_mode: 'DIRECT' }
}

function returnBody(expectedRevision = 1): {
  expected_revision: number
  comment: string
} {
  return { expected_revision: expectedRevision, comment: 'Комментарий' }
}

const idempotentHeaders = () => ({
  'X-CSRF-Token': CSRF,
  'Idempotency-Key': IDEMPOTENCY_PLACEHOLDER,
})
const csrfHeaders = () => ({ 'X-CSRF-Token': CSRF })

const callPublish = (api: WiseWayApiClient, body = publishBody()) =>
  api.POST('/dictionaries/{dictionary_id}/publish', {
    params: { path: { dictionary_id: 'dictionary-1' }, header: idempotentHeaders() },
    body,
  })

const callBatch = (api: WiseWayApiClient, body = batchBody()) =>
  api.POST('/sorting/batches', {
    params: { header: idempotentHeaders() },
    body,
  })

const callReturn = (api: WiseWayApiClient, body = returnBody()) =>
  api.POST('/quarantine/{quarantine_id}/return', {
    params: { path: { quarantine_id: 'quarantine-1' }, header: idempotentHeaders() },
    body,
  })

const callLogout = (api: WiseWayApiClient) =>
  api.POST('/auth/logout', { params: { header: csrfHeaders() } })

const callCreateDictionary = (api: WiseWayApiClient) =>
  api.POST('/companies/{company_id}/dictionaries', {
    params: { path: { company_id: 'company-1' }, header: csrfHeaders() },
    body: { name: 'Справочник', description: 'Описание' },
  })

const callReplaceDictionaryDraft = (api: WiseWayApiClient) =>
  api.PUT('/dictionaries/{dictionary_id}/draft', {
    params: { path: { dictionary_id: 'dictionary-1' }, header: csrfHeaders() },
    body: {
      expected_draft_revision: 0,
      name: 'Справочник',
      description: 'Описание',
      rules: [],
    },
  })

const callRestoreDictionaryDraft = (api: WiseWayApiClient) =>
  api.POST('/dictionaries/{dictionary_id}/restore-draft', {
    params: { path: { dictionary_id: 'dictionary-1' }, header: csrfHeaders() },
    body: { version_id: 'version-1', expected_draft_revision: 0 },
  })

const callCreateDictionarySimulation = (api: WiseWayApiClient) =>
  api.POST('/dictionaries/{dictionary_id}/simulate', {
    params: { path: { dictionary_id: 'dictionary-1' }, header: csrfHeaders() },
    body: { expected_draft_revision: 0 },
  })

const callCreateSortingSelection = (api: WiseWayApiClient) =>
  api.POST('/sorting/selections', {
    params: { header: csrfHeaders() },
    body: {
      company_id: 'company-1',
      mode: 'EXPLICIT',
      items: [{ item_id: 'item-1', item_revision: 1 }],
    },
  })

const callCreateSortingPreview = (api: WiseWayApiClient) =>
  api.POST('/sorting/previews', {
    params: { header: csrfHeaders() },
    body: { selection_id: 'selection-1' },
  })

const IDEMPOTENT_OPERATIONS: {
  operationId: string
  scope: string
  run: RunOperation
}[] = [
  {
    operationId: 'publishDictionary',
    scope: 'dictionary_id=dictionary-1',
    run: callPublish,
  },
  { operationId: 'createSortingBatch', scope: '', run: callBatch },
  {
    operationId: 'returnQuarantineItem',
    scope: 'quarantine_id=quarantine-1',
    run: callReturn,
  },
]

const NON_IDEMPOTENT_MUTATIONS: { operationId: string; run: RunOperation }[] = [
  { operationId: 'createDictionary', run: callCreateDictionary },
  { operationId: 'replaceDictionaryDraft', run: callReplaceDictionaryDraft },
  { operationId: 'restoreDictionaryDraft', run: callRestoreDictionaryDraft },
  {
    operationId: 'createDictionarySimulation',
    run: callCreateDictionarySimulation,
  },
  { operationId: 'createSortingSelection', run: callCreateSortingSelection },
  { operationId: 'createSortingPreview', run: callCreateSortingPreview },
  { operationId: 'logout', run: callLogout },
]

beforeEach(() => {
  resetSessionContext()
})

describe('IdempotencyStore: ключ связан с телом', () => {
  it('повтор того же тела возвращает тот же ключ', () => {
    const store = createIdempotencyStore()
    const body = publishBody()

    const first = store.begin('publishDictionary', body, 'dictionary_id=d1')
    const second = store.begin('publishDictionary', body, 'dictionary_id=d1')

    expect(first).toMatch(UUID_RE)
    expect(second).toBe(first)
  })

  it('изменённое тело даёт новый ключ, старый не переиспользуется', () => {
    const store = createIdempotencyStore()

    const first = store.begin('publishDictionary', publishBody('Первый'), 'd=d1')
    const changed = store.begin('publishDictionary', publishBody('Второй'), 'd=d1')
    const backToFirst = store.begin('publishDictionary', publishBody('Первый'), 'd=d1')

    expect(changed).not.toBe(first)
    // Прежнее тело после нового явного действия — это уже новая операция.
    expect(backToFirst).not.toBe(first)
    expect(backToFirst).not.toBe(changed)
  })

  it('complete освобождает действие: то же тело получает новый ключ', () => {
    const store = createIdempotencyStore()

    const first = store.begin('createSortingBatch', batchBody())
    store.complete('createSortingBatch')
    const second = store.begin('createSortingBatch', batchBody())

    expect(second).not.toBe(first)
  })

  it('retain сохраняет ожидающую запись для повтора', () => {
    const store = createIdempotencyStore()
    const body = returnBody()

    const first = store.begin('returnQuarantineItem', body, 'q=q1')
    const retained = store.retain('returnQuarantineItem', 'q=q1')
    const repeat = store.begin('returnQuarantineItem', body, 'q=q1')

    expect(retained?.key).toBe(first)
    expect(repeat).toBe(first)
  })

  it('retain без ожидающей записи не создаёт фиктивный ключ', () => {
    const store = createIdempotencyStore()

    expect(store.retain('publishDictionary', 'd=d1')).toBeUndefined()
  })

  it('clear очищает состояние', () => {
    const store = createIdempotencyStore()

    const first = store.begin('publishDictionary', publishBody())
    store.clear()
    const second = store.begin('publishDictionary', publishBody())

    expect(second).not.toBe(first)
  })

  it('scope изолирует разные ресурсы одной операции', () => {
    const store = createIdempotencyStore()
    const body = publishBody()

    const first = store.begin('publishDictionary', body, 'dictionary_id=d1')
    const other = store.begin('publishDictionary', body, 'dictionary_id=d2')

    expect(other).not.toBe(first)
    expect(store.begin('publishDictionary', body, 'dictionary_id=d1')).toBe(first)
  })
})

describe('fingerprintBody: детерминирован и не раскрывает тело', () => {
  it('не зависит от порядка ключей', () => {
    expect(fingerprintBody({ a: 1, b: 2 })).toBe(fingerprintBody({ b: 2, a: 1 }))
  })

  it('различает разные тела', () => {
    expect(fingerprintBody({ a: 1 })).not.toBe(fingerprintBody({ a: 2 }))
  })

  it('не содержит исходного тела/секрета', () => {
    const secret = 'synthetic-password-should-not-leak'
    const fingerprint = fingerprintBody({ password: secret })

    expect(fingerprint).not.toContain(secret)
    expect(fingerprint).toMatch(/^[0-9a-f]{16}$/)
  })

  it('не логирует тела и секреты', () => {
    const spies = [
      vi.spyOn(console, 'log').mockImplementation(() => {}),
      vi.spyOn(console, 'info').mockImplementation(() => {}),
      vi.spyOn(console, 'warn').mockImplementation(() => {}),
      vi.spyOn(console, 'error').mockImplementation(() => {}),
    ]
    const secret = 'synthetic-password-should-not-leak'
    const store = createIdempotencyStore()

    const key = store.begin('publishDictionary', { password: secret })
    const retained = store.retain('publishDictionary')

    expect(key).not.toContain(secret)
    expect(retained?.bodyFingerprint).not.toContain(secret)
    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    }
  })
})

describe('транспорт: Idempotency-Key ровно для 3 объявленных операций', () => {
  for (const { operationId, scope, run } of IDEMPOTENT_OPERATIONS) {
    it(`${operationId}: получает UUID-ключ, связанный с телом`, async () => {
      const store = createIdempotencyStore()
      const beginSpy = vi.spyOn(store, 'begin')
      const { api, requests } = setup({ store })

      await run(api)

      const header = lastRequest(requests).headers.get('Idempotency-Key')
      expect(header).toMatch(UUID_RE)
      expect(beginSpy).toHaveBeenCalledTimes(1)
      const [calledOperation, calledBody, calledScope] = beginSpy.mock.calls[0]
      expect(calledOperation).toBe(operationId)
      expect(JSON.parse(String(calledBody))).toEqual(lastRequest(requests).body)
      expect(calledScope).toBe(scope)
      expect(beginSpy.mock.results[0].value).toBe(header)
    })
  }

  for (const { operationId, run } of NON_IDEMPOTENT_MUTATIONS) {
    it(`${operationId}: не получает Idempotency-Key и не трогает store`, async () => {
      const store = createIdempotencyStore()
      const beginSpy = vi.spyOn(store, 'begin')
      const { api, requests } = setup({ store })

      await run(api)

      expect(lastRequest(requests).headers.get('Idempotency-Key')).toBeNull()
      expect(beginSpy).not.toHaveBeenCalled()
    })
  }
})

describe('транспорт: жизненный цикл ключа', () => {
  it('double-submit до ответа использует тот же key+body', async () => {
    const { api, requests } = setup()

    await Promise.all([callPublish(api), callPublish(api)])

    expect(requests).toHaveLength(2)
    expect(requests[1].headers.get('Idempotency-Key')).toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
    expect(requests[1].body).toEqual(requests[0].body)
  })

  it('изменённое тело при сохранённой pending-записи даёт новый ключ', async () => {
    const { api, requests } = setup({
      responders: [
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => okResponse(),
      ],
    })

    await callPublish(api, publishBody('Первый'))
    await callPublish(api, publishBody('Второй'))

    const [first, second] = requests
    expect(second.headers.get('Idempotency-Key')).not.toBe(
      first.headers.get('Idempotency-Key'),
    )
  })

  it('успех освобождает действие: то же тело получает новый ключ', async () => {
    const { api, requests } = setup({
      responders: [() => okResponse(), () => okResponse()],
    })

    await callPublish(api)
    await callPublish(api)

    const [first, second] = requests
    expect(second.headers.get('Idempotency-Key')).not.toBe(
      first.headers.get('Idempotency-Key'),
    )
  })

  it('сетевой сбой сохраняет ключ: повтор даёт тот же key+body', async () => {
    const { api, requests } = setup({
      responders: [
        () => {
          throw new TypeError('network down')
        },
        () => okResponse(),
      ],
    })

    await expect(callPublish(api)).rejects.toBeInstanceOf(TypeError)
    await callPublish(api)

    const [first, second] = requests
    expect(second.headers.get('Idempotency-Key')).toBe(
      first.headers.get('Idempotency-Key'),
    )
    expect(second.body).toEqual(first.body)
  })

  it('429 (retryable) сохраняет ключ', async () => {
    const { api, requests } = setup({
      responders: [
        () => errorResponse(429, 'RATE_LIMITED', true, { 'Retry-After': '1' }),
        () => okResponse(),
      ],
    })

    await callPublish(api)
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })

  it('503 (retryable) сохраняет ключ', async () => {
    const { api, requests } = setup({
      responders: [
        () => errorResponse(503, 'SERVICE_UNAVAILABLE', true),
        () => okResponse(),
      ],
    })

    await callPublish(api)
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })

  it('409 IDEMPOTENCY_KEY_REUSED (не-retryable) освобождает действие', async () => {
    const { api, requests } = setup({
      responders: [
        () => errorResponse(409, 'IDEMPOTENCY_KEY_REUSED', false),
        () => okResponse(),
      ],
    })

    await callPublish(api)
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).not.toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })

  it('422 (не-retryable) освобождает действие', async () => {
    const { api, requests } = setup({
      responders: [
        () => errorResponse(422, 'VALIDATION_ERROR', false),
        () => okResponse(),
      ],
    })

    await callPublish(api)
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).not.toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })
})

describe('транспорт: session-scope очистка', () => {
  it('clearSession очищает session-scoped store', async () => {
    const { api, requests } = setup({ defaultStore: true })

    await callPublish(api)
    clearSession()
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).not.toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })

  it('emitUnauthorized очищает session-scoped store', async () => {
    const { api, requests } = setup({ defaultStore: true })

    await callPublish(api)
    emitUnauthorized()
    await callPublish(api)

    expect(requests[1].headers.get('Idempotency-Key')).not.toBe(
      requests[0].headers.get('Idempotency-Key'),
    )
  })
})
