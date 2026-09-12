// LT-06.2a-ii: mock HTTP handlers `searchFiles`/`getSearchFacet` над golden
// foundation.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` — тот же
// транспорт/session/error-слой, что и real. HTTP-ответы сравниваются с literal
// golden `search_expectations.json` (IDLE/zero/limited/RESULTS/UNRECOGNIZED/
// freshness), а не с повторным вызовом resolver'а: handler обязан отдавать
// ровно эталонные totals/order/facets. Невалидные/неизвестные запросы и запросы
// без сессии дают объявленную ошибку, а не правдоподобный успех. Отдельно
// проверяется, что поиск не инициирует иных (mutation/batch) запросов.

import searchExpectationsFixture from '@fixtures/synthetic/search_expectations.json'
import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  createMockFetch,
  MOCK_MARKER_HEADER,
  MOCK_MODE,
  MockController,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import type {
  ErrorResponse,
  FacetRequest,
  LoginRequest,
  SearchRequest,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface GoldenSearchScenario {
  scenario_id: string
  request: {
    request_state_id: string
    root_id: string
    selected_marker_ids: string[]
    query_text: string
    sort: { field: string; direction: string }
    facet_prefix: string
  }
  expected: {
    mode: 'IDLE' | 'RESULTS'
    total: number | null
    returned_count: number
    result_limit: number
    limited: boolean
    applied_query_text: string
    item_ids: string[]
    next_facet: {
      level_id: string
      level_name: string
      options: { marker_id: string; count: number }[]
    } | null
  }
  freshness_profile?: 'CURRENT' | 'UPDATING' | 'STALE'
}

interface GoldenFacetScenario {
  scenario_id: string
  request: {
    request_state_id: string
    root_id: string
    selected_marker_ids: string[]
    query_text: string
    facet_prefix: string
  }
  expected: {
    facet_level_id: string | null
    options: { marker_id: string; count: number }[]
  }
}

interface GoldenConstants {
  ranking_profile_version: string
  freshness_profiles: Record<
    string,
    { indexed_at: string; last_successful_sync_at: string; status: string }
  >
  roots: Record<string, { schema_set_version: string; index_generation: string }>
  level_names: Record<string, string>
}

interface GoldenFile {
  constants: GoldenConstants
  search_scenarios: GoldenSearchScenario[]
  facet_scenarios: GoldenFacetScenario[]
}

const golden = searchExpectationsFixture as unknown as GoldenFile

function findSearch(scenarioId: string): GoldenSearchScenario {
  const scenario = golden.search_scenarios.find(
    (candidate) => candidate.scenario_id === scenarioId,
  )
  if (!scenario) {
    throw new Error(`Golden search-сценарий "${scenarioId}" не найден`)
  }
  return scenario
}

function findFacet(scenarioId: string): GoldenFacetScenario {
  const scenario = golden.facet_scenarios.find(
    (candidate) => candidate.scenario_id === scenarioId,
  )
  if (!scenario) {
    throw new Error(`Golden facet-сценарий "${scenarioId}" не найден`)
  }
  return scenario
}

function optionKeys(
  options: { marker_id: string; count: number }[],
): { marker_id: string; count: number }[] {
  return options.map((option) => ({
    marker_id: option.marker_id,
    count: option.count,
  }))
}

function searchBody(
  scenario: GoldenSearchScenario,
  overrides: Partial<SearchRequest> = {},
): SearchRequest {
  return {
    request_state_id: scenario.request.request_state_id,
    root_id: scenario.request.root_id,
    schema_set_version:
      golden.constants.roots[scenario.request.root_id].schema_set_version,
    selected_marker_ids: scenario.request.selected_marker_ids,
    query_text: scenario.request.query_text,
    sort: scenario.request.sort as SearchRequest['sort'],
    facet_prefix: scenario.request.facet_prefix,
    ...overrides,
  }
}

function facetBody(
  scenario: GoldenFacetScenario,
  overrides: Partial<FacetRequest> = {},
): FacetRequest {
  return {
    request_state_id: scenario.request.request_state_id,
    root_id: scenario.request.root_id,
    schema_set_version:
      golden.constants.roots[scenario.request.root_id].schema_set_version,
    selected_marker_ids: scenario.request.selected_marker_ids,
    query_text: scenario.request.query_text,
    facet_prefix: scenario.request.facet_prefix,
    ...overrides,
  }
}

interface RecordedCall {
  method: string
  path: string
  csrf: string | null
  idempotencyKey: string | null
}

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
  calls: RecordedCall[]
}

function setup(): Setup {
  const calls: RecordedCall[] = []
  const controller = new MockController({ sleep: async () => {} })
  const baseFetch = createMockFetch(controller)
  const mockFetch: MockFetch = async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url, 'http://localhost')
    calls.push({
      method: request.method.toUpperCase(),
      path: url.pathname,
      csrf: request.headers.get('X-CSRF-Token'),
      idempotencyKey: request.headers.get('Idempotency-Key'),
    })
    return baseFetch(request)
  }
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
  })
  return { controller, mockFetch, api, calls }
}

function request(path: string, init?: RequestInit): Request {
  return new Request(`http://localhost/api/v1${path}`, init)
}

async function readError(response: Response): Promise<ErrorResponse> {
  return (await response.json()) as ErrorResponse
}

async function loginWorkerOne(api: WiseWayApiClient): Promise<void> {
  const body = getExample<LoginRequest>('auth-login-request-worker-one')
  const result = await api.POST('/auth/login', { body })
  expect(result.response.status).toBe(200)
}

beforeEach(() => {
  resetSessionContext()
})

describe('searchFiles: success-состояния через HTTP-слой', () => {
  it('IDLE Atlas → literal golden IDLE (items=[], total=null, первый facet)', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q004-IDLE-ATLAS')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(data).toBeDefined()
    if (!data) {
      return
    }
    expect(validateSchema('SearchResponse', data).valid).toBe(true)
    expect(data.request_state_id).toBe('srch-q004-idle-atlas')
    expect(data.mode).toBe('IDLE')
    expect(data.total).toBeNull()
    expect(data.items).toEqual([])
    expect(data.selected_markers).toEqual([])
    expect(data.returned_count).toBe(0)
    expect(data.result_limit).toBe(100)
    expect(data.limited).toBe(false)
    expect(data.applied_query_text).toBe('')
    expect(data.root_id).toBe('root-demo-atlas')
    expect(data.schema_set_version).toBe('schema-demo-1')
    expect(data.index_generation).toBe('generation-demo-1')
    expect(data.ranking_profile_version).toBe(
      golden.constants.ranking_profile_version,
    )
    expect(data.freshness).toEqual(golden.constants.freshness_profiles.CURRENT)
    expect(data.next_facet?.level_id).toBe('level-section')
    expect(data.next_facet?.level_name).toBe('Раздел')
    expect(optionKeys(data.next_facet?.options ?? [])).toEqual([
      { marker_id: 'marker-root-demo-atlas-archive', count: 151 },
    ])
  })

  it('zero → RESULTS total=0, items=[], пустой первый facet', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q004-ZERO')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(data?.mode).toBe('RESULTS')
    expect(data?.total).toBe(0)
    expect(data?.returned_count).toBe(0)
    expect(data?.limited).toBe(false)
    expect(data?.items).toEqual([])
    expect(data?.next_facet?.level_id).toBe('level-section')
    expect(data?.next_facet?.options).toEqual([])
    expect(validateSchema('SearchResponse', data).valid).toBe(true)
  })

  it('limited N=10 → literal total/returned_count/order', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q013-N10')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(data?.mode).toBe('RESULTS')
    expect(data?.total).toBe(13)
    expect(data?.returned_count).toBe(10)
    expect(data?.result_limit).toBe(10)
    expect(data?.limited).toBe(true)
    expect(data?.items.map((item) => item.item_id)).toEqual(
      scenario.expected.item_ids,
    )
    expect(data?.items).toHaveLength(10)
    expect(optionKeys(data?.next_facet?.options ?? [])).toEqual([
      { marker_id: 'marker-root-demo-nova-archive', count: 13 },
    ])
    expect(validateSchema('SearchResponse', data).valid).toBe(true)
  })

  it('RESULTS с marker+text → literal order/selected_markers, next_facet=null', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q007-MARKER-AND')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(data?.mode).toBe('RESULTS')
    expect(data?.total).toBe(6)
    expect(data?.items.map((item) => item.item_id)).toEqual(
      scenario.expected.item_ids,
    )
    expect(data?.selected_markers.map((marker) => marker.marker_id)).toEqual(
      scenario.request.selected_marker_ids,
    )
    expect(data?.next_facet).toBeNull()
    expect(validateSchema('SearchResponse', data).valid).toBe(true)
  })

  it('UNRECOGNIZED-терминал → item со structure_issue и next_facet=null', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q012-UNRECOGNIZED-TERMINAL')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(data?.total).toBe(1)
    expect(data?.items[0]?.item_id).toBe('file-atlas-issue-invalid-value')
    expect(data?.items[0]?.structure_status).toBe('UNRECOGNIZED')
    expect(data?.items[0]?.structure_issue?.code).toBe('INVALID_LEVEL_VALUE')
    expect(data?.next_facet).toBeNull()
    expect(validateSchema('SearchResponse', data).valid).toBe(true)
  })

  it('контрактные заголовки и mock-маркер', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q004-IDLE-ATLAS')

    const result = await api.POST('/search', { body: searchBody(scenario) })

    expect(result.response.headers.get('Content-Type')).toContain(
      'application/json',
    )
    expect(result.response.headers.get('Cache-Control')).toBe('no-store')
    expect(result.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
    expect(result.response.headers.get(MOCK_MARKER_HEADER)).toBe(MOCK_MODE)
  })
})

describe('getSearchFacet: переоткрытие уровня', () => {
  it('возвращает literal options/counts открытого уровня', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findFacet('FACET-Q006-NOVA-ORION-NORTH')

    const result = await api.POST('/search/facet', {
      body: facetBody(scenario),
    })

    expect(result.response.status).toBe(200)
    const data = result.data
    expect(validateSchema('FacetResponse', data).valid).toBe(true)
    expect(data?.request_state_id).toBe('facet-q006-nova-orion-north')
    expect(data?.root_id).toBe('root-demo-nova')
    expect(data?.schema_set_version).toBe('schema-demo-2')
    expect(data?.index_generation).toBe('generation-demo-2')
    expect(data?.facet?.level_id).toBe('level-category')
    expect(data?.facet?.level_name).toBe(
      golden.constants.level_names['level-category'],
    )
    expect(optionKeys(data?.facet?.options ?? [])).toEqual([
      {
        marker_id:
          'marker-root-demo-nova-archive-nova-orion-north-data',
        count: 1,
      },
      {
        marker_id:
          'marker-root-demo-nova-archive-nova-orion-north-reports',
        count: 7,
      },
    ])
  })
})

describe('request_state_id echo', () => {
  it('search возвращает ровно присланный request_state_id', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q004-IDLE-ATLAS')

    const result = await api.POST('/search', {
      body: searchBody(scenario, { request_state_id: 'state-echo-search-1' }),
    })

    expect(result.response.status).toBe(200)
    expect(result.data?.request_state_id).toBe('state-echo-search-1')
  })

  it('facet возвращает ровно присланный request_state_id', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const scenario = findFacet('FACET-Q006-NOVA-ORION-NORTH')

    const result = await api.POST('/search/facet', {
      body: facetBody(scenario, { request_state_id: 'state-echo-facet-1' }),
    })

    expect(result.response.status).toBe(200)
    expect(result.data?.request_state_id).toBe('state-echo-facet-1')
  })
})

describe('freshness-профиль', () => {
  it('STALE/UPDATING отражаются, reset() возвращает CURRENT', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    const scenario = findSearch('SRCH-Q011-RANK-FULL')
    // request_state_id не из golden: профиль выбирает коллизию условий
    // nova/atlas/RELEVANCE/DESC (CURRENT/UPDATING/STALE).
    const body = searchBody(scenario, {
      request_state_id: 'state-freshness-arbitrary',
    })

    controller.setSearchFreshnessProfile('STALE')
    const stale = await api.POST('/search', { body })
    expect(stale.response.status).toBe(200)
    expect(stale.data?.freshness.status).toBe('STALE')
    expect(stale.data?.freshness).toEqual(
      golden.constants.freshness_profiles.STALE,
    )
    expect(stale.data?.items.map((item) => item.item_id)).toEqual(
      scenario.expected.item_ids,
    )

    controller.setSearchFreshnessProfile('UPDATING')
    const updating = await api.POST('/search', { body })
    expect(updating.response.status).toBe(200)
    expect(updating.data?.freshness.status).toBe('UPDATING')
    expect(updating.data?.freshness).toEqual(
      golden.constants.freshness_profiles.UPDATING,
    )

    controller.reset()
    expect(controller.getSearchFreshnessProfile()).toBe('CURRENT')

    await loginWorkerOne(api)
    const current = await api.POST('/search', { body })
    expect(current.data?.freshness).toEqual(
      golden.constants.freshness_profiles.CURRENT,
    )
  })
})

describe('невалидный и неизвестный запрос не даёт success', () => {
  it('search без root_id → 422 VALIDATION_ERROR', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)
    const body = { ...searchBody(findSearch('SRCH-Q004-IDLE-ATLAS')) } as Record<
      string,
      unknown
    >
    delete body.root_id

    const response = await mockFetch(
      request('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    )

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.map((item) => item.field)).toContain(
      'root_id',
    )
    expect(validateSchema('ErrorResponse', error).valid).toBe(true)
  })

  it('search с лишним полем → 422 VALIDATION_ERROR', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)
    const body = {
      ...searchBody(findSearch('SRCH-Q004-IDLE-ATLAS')),
      extra: 'unknown',
    }

    const response = await mockFetch(
      request('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    )

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.map((item) => item.field)).toContain('extra')
  })

  it('search с битым JSON → 422, не ложный успех', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)

    const response = await mockFetch(
      request('/search', { method: 'POST', body: '{not-json' }),
    )

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors[0]?.field).toBe('request')
  })

  it('search RELEVANCE с пустым query_text → 422 по условию OAS', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)
    const body = searchBody(findSearch('SRCH-Q004-IDLE-ATLAS'), {
      query_text: '',
      sort: { field: 'RELEVANCE', direction: 'DESC' },
    })

    const response = await mockFetch(
      request('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    )

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(validateSchema('ErrorResponse', error).valid).toBe(true)
  })

  it('facet без root_id → 422 VALIDATION_ERROR', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)
    const body = {
      ...facetBody(findFacet('FACET-Q006-NOVA-ORION-NORTH')),
    } as Record<string, unknown>
    delete body.root_id

    const response = await mockFetch(
      request('/search/facet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    )

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.map((item) => item.field)).toContain(
      'root_id',
    )
  })

  it('валидный search без golden-сценария → 400 INVALID_QUERY', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const body: SearchRequest = {
      request_state_id: 'request-unknown-search',
      root_id: 'root-demo-atlas',
      schema_set_version: 'schema-demo-1',
      selected_marker_ids: [],
      query_text: 'archive',
      sort: { field: 'RELEVANCE', direction: 'DESC' },
      facet_prefix: '',
    }

    const result = await api.POST('/search', { body })

    expect(result.response.status).toBe(400)
    expect(result.error?.error.code).toBe('INVALID_QUERY')
    expect(validateSchema('ErrorResponse', result.error).valid).toBe(true)
  })

  it('валидный facet без golden-сценария → 400 INVALID_QUERY', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const body: FacetRequest = {
      request_state_id: 'request-unknown-facet',
      root_id: 'root-demo-atlas',
      schema_set_version: 'schema-demo-1',
      selected_marker_ids: [],
      query_text: '',
      facet_prefix: '',
    }

    const result = await api.POST('/search/facet', { body })

    expect(result.response.status).toBe(400)
    expect(result.error?.error.code).toBe('INVALID_QUERY')
  })
})

describe('сессия и отсутствие иных запросов', () => {
  it('search/facet без сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()

    const search = await api.POST('/search', {
      body: searchBody(findSearch('SRCH-Q004-IDLE-ATLAS')),
    })
    const facet = await api.POST('/search/facet', {
      body: facetBody(findFacet('FACET-Q006-NOVA-ORION-NORTH')),
    })

    expect(search.response.status).toBe(401)
    expect(search.error?.error.code).toBe('UNAUTHENTICATED')
    expect(facet.response.status).toBe(401)
    expect(facet.error?.error.code).toBe('UNAUTHENTICATED')
  })

  it('поиск не инициирует mutation/batch POST и не несёт CSRF/Idempotency-Key', async () => {
    const { api, calls } = setup()
    await loginWorkerOne(api)
    calls.length = 0

    const search = await api.POST('/search', {
      body: searchBody(findSearch('SRCH-Q004-IDLE-ATLAS')),
    })
    const facet = await api.POST('/search/facet', {
      body: facetBody(findFacet('FACET-Q006-NOVA-ORION-NORTH')),
    })

    expect(search.response.status).toBe(200)
    expect(facet.response.status).toBe(200)
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      'POST /api/v1/search',
      'POST /api/v1/search/facet',
    ])
    for (const call of calls) {
      expect(call.csrf).toBeNull()
      expect(call.idempotencyKey).toBeNull()
    }
  })
})
