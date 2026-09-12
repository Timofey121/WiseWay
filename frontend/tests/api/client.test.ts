import { describe, expect, it, vi } from 'vitest'

import { createWiseWayClient } from '@/api/generated/client'

// Runtime-проверки типизированного клиента. `fetch` подменён записывающим
// стабом: тесты проверяют фактически сформированные method/path/query/body/
// headers для операций A/B/C, а не поведение сети.

interface RecordedRequest {
  method: string
  pathname: string
  searchParams: URLSearchParams
  headers: Headers
  body: unknown
}

function setup() {
  const requests: RecordedRequest[] = []
  const fetchStub = vi.fn(async (input: Request): Promise<Response> => {
    const rawBody = await input.clone().text()
    const url = new URL(input.url)
    requests.push({
      method: input.method,
      pathname: url.pathname,
      searchParams: url.searchParams,
      headers: input.headers,
      body: rawBody === '' ? undefined : JSON.parse(rawBody),
    })
    return new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  const api = createWiseWayClient({
    baseUrl: 'http://localhost/api/v1',
    fetch: fetchStub,
  })

  return { api, requests }
}

function lastRequest(requests: RecordedRequest[]): RecordedRequest {
  const request = requests.at(-1)
  if (!request) {
    throw new Error('Клиент не выполнил ни одного запроса')
  }
  return request
}

const CSRF = 'synthetic-csrf-token-example'
const IDEMPOTENCY_KEY = '78d74c30-0db1-4d3c-8f23-13f721f53336'

describe('клиент A: auth/config/roots/search', () => {
  it('getHealth: GET /health без тела', async () => {
    const { api, requests } = setup()

    await api.GET('/health')

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/health')
    expect(request.body).toBeUndefined()
  })

  it('login: POST /auth/login с телом {login, password}', async () => {
    const { api, requests } = setup()

    await api.POST('/auth/login', {
      body: { login: 'worker-atlas', password: 'synthetic-password-example' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/auth/login')
    expect(request.headers.get('Content-Type')).toBe('application/json')
    expect(request.body).toEqual({
      login: 'worker-atlas',
      password: 'synthetic-password-example',
    })
  })

  it('getSession: GET /session', async () => {
    const { api, requests } = setup()

    await api.GET('/session')

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/session')
  })

  it('listRoots: GET /roots', async () => {
    const { api, requests } = setup()

    await api.GET('/roots')

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/roots')
  })

  it('searchFiles: POST /search с телом SearchRequest', async () => {
    const { api, requests } = setup()

    await api.POST('/search', {
      body: {
        request_state_id: 'state-demo-1',
        root_id: 'root-demo-1',
        schema_set_version: 'schema-demo-1',
        selected_marker_ids: [],
        query_text: 'atlas 2031',
        sort: { field: 'RELEVANCE', direction: 'DESC' },
        facet_prefix: '',
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/search')
    expect(request.body).toMatchObject({
      request_state_id: 'state-demo-1',
      query_text: 'atlas 2031',
      selected_marker_ids: [],
    })
  })

  it('getSearchFacet: POST /search/facet с телом FacetRequest', async () => {
    const { api, requests } = setup()

    await api.POST('/search/facet', {
      body: {
        request_state_id: 'state-facet-1',
        root_id: 'root-demo-1',
        schema_set_version: 'schema-demo-1',
        selected_marker_ids: ['marker-archive'],
        query_text: 'atlas 2031',
        facet_prefix: 'at',
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/search/facet')
    expect(request.body).toMatchObject({ facet_prefix: 'at' })
  })
})

describe('клиент B: targets/dictionaries/simulations/publish', () => {
  it('listTargetDirectories: path company_id и query limit', async () => {
    const { api, requests } = setup()

    await api.GET('/companies/{company_id}/target-directories', {
      params: { path: { company_id: 'company-demo-1' }, query: { limit: 50 } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe(
      '/api/v1/companies/company-demo-1/target-directories',
    )
    expect(request.searchParams.get('limit')).toBe('50')
  })

  it('resolveTargetDirectory: POST с display_path', async () => {
    const { api, requests } = setup()

    await api.POST('/companies/{company_id}/target-directories/resolve', {
      params: { path: { company_id: 'company-demo-1' } },
      body: { display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Reports' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe(
      '/api/v1/companies/company-demo-1/target-directories/resolve',
    )
    expect(request.body).toEqual({
      display_path: 'DEMO:/SandboxRoot/Archive/Atlas/Reports',
    })
  })

  it('listDictionaries: GET с path company_id', async () => {
    const { api, requests } = setup()

    await api.GET('/companies/{company_id}/dictionaries', {
      params: { path: { company_id: 'company-demo-1' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe(
      '/api/v1/companies/company-demo-1/dictionaries',
    )
  })

  it('createDictionary: POST с CSRF-заголовком и телом', async () => {
    const { api, requests } = setup()

    await api.POST('/companies/{company_id}/dictionaries', {
      params: {
        path: { company_id: 'company-demo-1' },
        header: { 'X-CSRF-Token': CSRF },
      },
      body: { name: 'Счета Atlas', description: 'Правила для счетов' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.body).toEqual({
      name: 'Счета Atlas',
      description: 'Правила для счетов',
    })
    expect(request.body).not.toHaveProperty('X-CSRF-Token')
  })

  it('getDictionary: GET с path dictionary_id', async () => {
    const { api, requests } = setup()

    await api.GET('/dictionaries/{dictionary_id}', {
      params: { path: { dictionary_id: 'dictionary-demo-1' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/dictionaries/dictionary-demo-1')
  })

  it('replaceDictionaryDraft: PUT с CSRF и телом', async () => {
    const { api, requests } = setup()

    await api.PUT('/dictionaries/{dictionary_id}/draft', {
      params: {
        path: { dictionary_id: 'dictionary-demo-1' },
        header: { 'X-CSRF-Token': CSRF },
      },
      body: {
        expected_draft_revision: 2,
        name: 'Счета Atlas',
        description: 'Правила для счетов',
        rules: [],
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('PUT')
    expect(request.pathname).toBe(
      '/api/v1/dictionaries/dictionary-demo-1/draft',
    )
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.body).toMatchObject({ expected_draft_revision: 2, rules: [] })
  })

  it('createDictionarySimulation: POST с CSRF и ревизией', async () => {
    const { api, requests } = setup()

    await api.POST('/dictionaries/{dictionary_id}/simulate', {
      params: {
        path: { dictionary_id: 'dictionary-demo-1' },
        header: { 'X-CSRF-Token': CSRF },
      },
      body: { expected_draft_revision: 2 },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe(
      '/api/v1/dictionaries/dictionary-demo-1/simulate',
    )
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.body).toEqual({ expected_draft_revision: 2 })
  })

  it('getSimulation: GET с path и query limit', async () => {
    const { api, requests } = setup()

    await api.GET('/simulations/{simulation_id}', {
      params: {
        path: { simulation_id: 'simulation-demo-1' },
        query: { limit: 100 },
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/simulations/simulation-demo-1')
    expect(request.searchParams.get('limit')).toBe('100')
  })

  it('publishDictionary: POST с CSRF, Idempotency-Key и телом', async () => {
    const { api, requests } = setup()

    await api.POST('/dictionaries/{dictionary_id}/publish', {
      params: {
        path: { dictionary_id: 'dictionary-demo-1' },
        header: {
          'X-CSRF-Token': CSRF,
          'Idempotency-Key': IDEMPOTENCY_KEY,
        },
      },
      body: {
        expected_draft_revision: 2,
        simulation_id: 'simulation-demo-1',
        acknowledge_no_scenario: false,
        comment: 'Проверено на готовых файлах',
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe(
      '/api/v1/dictionaries/dictionary-demo-1/publish',
    )
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.headers.get('Idempotency-Key')).toBe(IDEMPOTENCY_KEY)
    expect(request.body).toMatchObject({
      simulation_id: 'simulation-demo-1',
      acknowledge_no_scenario: false,
    })
    expect(request.body).not.toHaveProperty('Idempotency-Key')
  })
})

describe('клиент C: queue/selections/previews/batches/quarantine/audit', () => {
  it('querySortingQueue: POST с телом QueueQueryRequest', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/queue/query', {
      body: {
        company_id: 'company-atlas',
        filters: { statuses: ['READY'], query_text: 'report' },
        cursor: null,
        limit: 50,
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/sorting/queue/query')
    expect(request.body).toMatchObject({
      company_id: 'company-atlas',
      filters: { statuses: ['READY'] },
    })
  })

  it('createSortingSelection: EXPLICIT-тело', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/selections', {
      params: { header: { 'X-CSRF-Token': CSRF } },
      body: {
        company_id: 'company-atlas',
        mode: 'EXPLICIT',
        items: [{ item_id: 'item-001', item_revision: 3 }],
      },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/sorting/selections')
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.body).toEqual({
      company_id: 'company-atlas',
      mode: 'EXPLICIT',
      items: [{ item_id: 'item-001', item_revision: 3 }],
    })
  })

  it('createSortingSelection: ALL_MATCHING-тело', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/selections', {
      params: { header: { 'X-CSRF-Token': CSRF } },
      body: {
        company_id: 'company-atlas',
        mode: 'ALL_MATCHING',
        filters: { statuses: ['READY'], query_text: '' },
        expected_eligible_count: 120,
      },
    })

    const request = lastRequest(requests)
    expect(request.body).toMatchObject({
      mode: 'ALL_MATCHING',
      expected_eligible_count: 120,
    })
  })

  it('createSortingPreview: POST с selection_id', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/previews', {
      params: { header: { 'X-CSRF-Token': CSRF } },
      body: { selection_id: 'selection-001' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/sorting/previews')
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.body).toEqual({ selection_id: 'selection-001' })
  })

  it('getSortingPreview: GET с path preview_id', async () => {
    const { api, requests } = setup()

    await api.GET('/sorting/previews/{preview_id}', {
      params: { path: { preview_id: 'preview-001' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/sorting/previews/preview-001')
  })

  it('createSortingBatch: DIRECT не передаёт preview_id', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/batches', {
      params: {
        header: { 'X-CSRF-Token': CSRF, 'Idempotency-Key': IDEMPOTENCY_KEY },
      },
      body: { selection_id: 'selection-001', execution_mode: 'DIRECT' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/sorting/batches')
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.headers.get('Idempotency-Key')).toBe(IDEMPOTENCY_KEY)
    expect(request.body).toEqual({
      selection_id: 'selection-001',
      execution_mode: 'DIRECT',
    })
    expect(request.body).not.toHaveProperty('preview_id')
  })

  it('createSortingBatch: PREVIEWED передаёт preview_id', async () => {
    const { api, requests } = setup()

    await api.POST('/sorting/batches', {
      params: {
        header: { 'X-CSRF-Token': CSRF, 'Idempotency-Key': IDEMPOTENCY_KEY },
      },
      body: {
        selection_id: 'selection-001',
        execution_mode: 'PREVIEWED',
        preview_id: 'preview-001',
      },
    })

    const request = lastRequest(requests)
    expect(request.body).toEqual({
      selection_id: 'selection-001',
      execution_mode: 'PREVIEWED',
      preview_id: 'preview-001',
    })
    expect(request.headers.get('Idempotency-Key')).toBe(IDEMPOTENCY_KEY)
    expect(request.body).not.toHaveProperty('Idempotency-Key')
  })

  it('getSortingBatch: GET с path batch_id', async () => {
    const { api, requests } = setup()

    await api.GET('/sorting/batches/{batch_id}', {
      params: { path: { batch_id: 'batch-001' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/sorting/batches/batch-001')
  })

  it('listSortingBatches: query company_id обязателен и передаётся', async () => {
    const { api, requests } = setup()

    await api.GET('/sorting/batches', {
      params: { query: { company_id: 'company-atlas' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/sorting/batches')
    expect(request.searchParams.get('company_id')).toBe('company-atlas')
  })

  it('listQuarantineItems: query company_id обязателен и передаётся', async () => {
    const { api, requests } = setup()

    await api.GET('/quarantine', {
      params: { query: { company_id: 'company-atlas' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/quarantine')
    expect(request.searchParams.get('company_id')).toBe('company-atlas')
  })

  it('returnQuarantineItem: POST с CSRF, Idempotency-Key и телом', async () => {
    const { api, requests } = setup()

    await api.POST('/quarantine/{quarantine_id}/return', {
      params: {
        path: { quarantine_id: 'quarantine-001' },
        header: { 'X-CSRF-Token': CSRF, 'Idempotency-Key': IDEMPOTENCY_KEY },
      },
      body: { expected_revision: 1, comment: 'Повторно проверить.' },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe(
      '/api/v1/quarantine/quarantine-001/return',
    )
    expect(request.headers.get('X-CSRF-Token')).toBe(CSRF)
    expect(request.headers.get('Idempotency-Key')).toBe(IDEMPOTENCY_KEY)
    expect(request.body).toEqual({
      expected_revision: 1,
      comment: 'Повторно проверить.',
    })
  })

  it('queryAuditEvents: POST с телом AuditQueryRequest', async () => {
    const { api, requests } = setup()

    await api.POST('/audit/query', {
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
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('POST')
    expect(request.pathname).toBe('/api/v1/audit/query')
    expect(request.body).toMatchObject({
      from: '2031-05-10T00:00:00Z',
      limit: 100,
    })
  })

  it('getAuditUpdates: GET с query after_event_id', async () => {
    const { api, requests } = setup()

    await api.GET('/audit/updates', {
      params: { query: { after_event_id: 'event-001' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/audit/updates')
    expect(request.searchParams.get('after_event_id')).toBe('event-001')
  })

  it('listAuditActors: GET с query prefix', async () => {
    const { api, requests } = setup()

    await api.GET('/audit/actors', {
      params: { query: { prefix: 'work' } },
    })

    const request = lastRequest(requests)
    expect(request.method).toBe('GET')
    expect(request.pathname).toBe('/api/v1/audit/actors')
    expect(request.searchParams.get('prefix')).toBe('work')
  })
})
