// LT-06.2b: управляемые delay/error/race сценарии mock-поиска.
//
// Проверяется mock-управление, а не UI-логика гонки (она относится к WP-13):
// отдельные scope `search` (таблица) и `facet` (список уровня), объявленные
// контрактом ошибки из `contracts/examples/errors/*.json`, детерминированный
// порядок ответов через per-send задержки и точный `request_state_id` каждой
// отправки.
//
// Ожидания не ждут реально: `MockController` принимает инъектированный `sleep`,
// а race-порядок управляется `ManualClock`. Для 503 отдельно проверяется, что
// транспорт с `retry: { maxAttempts: 1 }` не превращает ошибку в успех.

import searchExpectationsFixture from '@fixtures/synthetic/search_expectations.json'
import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext } from '@/api/session-context'
import { createApiClient } from '@/api/transport'
import {
  createMockFetch,
  declaredSearchErrors,
  MockController,
  type MockFetch,
  type SearchErrorCode,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import type {
  ErrorResponse,
  FacetRequest,
  LoginRequest,
  SearchRequest,
  Session,
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
    item_ids: string[]
  }
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
  expected: { facet_level_id: string | null }
}

interface GoldenConstants {
  roots: Record<string, { schema_set_version: string }>
}

interface GoldenFile {
  constants: GoldenConstants
  search_scenarios: GoldenSearchScenario[]
  facet_scenarios: GoldenFacetScenario[]
}

const golden = searchExpectationsFixture as unknown as GoldenFile

const SEARCH_SCENARIO = 'SRCH-Q004-IDLE-ATLAS'
const FACET_SCENARIO = 'FACET-Q006-NOVA-ORION-NORTH'

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

function request(path: string, init?: RequestInit): Request {
  return new Request(`http://localhost/api/v1${path}`, init)
}

function postJson(
  mockFetch: MockFetch,
  path: string,
  body: unknown,
): Promise<Response> {
  return mockFetch(
    request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

async function readError(response: Response): Promise<ErrorResponse> {
  return (await response.json()) as ErrorResponse
}

/** Детерминированные часы: `sleep` блокируется до ручного `advance`. */
class ManualClock {
  private pending: { at: number; order: number; resolve: () => void }[] = []
  private time = 0
  private order = 0

  readonly sleep = (ms: number): Promise<void> => {
    if (ms <= 0) {
      return Promise.resolve()
    }
    return new Promise<void>((resolve) => {
      this.pending.push({ at: this.time + ms, order: this.order, resolve })
      this.order += 1
    })
  }

  /** Крутит микрозадачи, пока условие не выполнится (ограниченно). */
  async waitUntil(condition: () => boolean): Promise<void> {
    for (let i = 0; i < 200 && !condition(); i += 1) {
      await Promise.resolve()
    }
  }

  /** Пропускает микрозадачи, чтобы разрешённые handlers завершились. */
  private async flush(): Promise<void> {
    for (let i = 0; i < 50; i += 1) {
      await Promise.resolve()
    }
  }

  /** Разрешает ожидания с дедлайном ≤ `time + ms` в порядке at, затем order. */
  async advance(ms: number): Promise<void> {
    this.time += ms
    const due = this.pending
      .filter((entry) => entry.at <= this.time)
      .sort((a, b) => a.at - b.at || a.order - b.order)
    this.pending = this.pending.filter((entry) => entry.at > this.time)
    for (const entry of due) {
      entry.resolve()
    }
    await this.flush()
  }

  get pendingCount(): number {
    return this.pending.length
  }
}

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  sleeps: number[]
}

/**
 * Готовит mock-fetch с активной mock-сессией. `sleepImpl` подменяет ожидание
 * (ManualClock); запрошенные задержки всё равно записываются в `sleeps`.
 */
function setup(sleepImpl?: (ms: number) => Promise<void>): Setup {
  const sleeps: number[] = []
  const controller = new MockController({
    sleep: (ms) => {
      sleeps.push(ms)
      return sleepImpl ? sleepImpl(ms) : Promise.resolve()
    },
  })
  const mockFetch = createMockFetch(controller)
  controller.setSession(getExample<Session>('auth-session-worker-one'))
  return { controller, mockFetch, sleeps }
}

const declaredCodes = Object.keys(declaredSearchErrors) as SearchErrorCode[]

beforeEach(() => {
  resetSessionContext()
})

describe('scope-delay: search (таблица) и facet (dropdown) независимы', () => {
  it('setScopeDelay("facet", X) задерживает только facet', async () => {
    const { controller, mockFetch, sleeps } = setup()
    controller.setScopeDelay('facet', 40)

    const search = await postJson(mockFetch, '/search', searchBody(findSearch(SEARCH_SCENARIO)))
    const facet = await postJson(
      mockFetch,
      '/search/facet',
      facetBody(findFacet(FACET_SCENARIO)),
    )

    expect(search.status).toBe(200)
    expect(facet.status).toBe(200)
    expect(sleeps).toEqual([40])
    expect(controller.getScopeDelay('search')).toBe(0)
    expect(controller.getScopeDelay('facet')).toBe(40)
  })

  it('setScopeDelay("search", X) задерживает только таблицу', async () => {
    const { controller, mockFetch, sleeps } = setup()
    controller.setScopeDelay('search', 25)

    const search = await postJson(mockFetch, '/search', searchBody(findSearch(SEARCH_SCENARIO)))
    const facet = await postJson(
      mockFetch,
      '/search/facet',
      facetBody(findFacet(FACET_SCENARIO)),
    )

    expect(search.status).toBe(200)
    expect(facet.status).toBe(200)
    expect(sleeps).toEqual([25])
  })

  it('очередь per-send расходуется по порядку и возвращается к базовой задержке', async () => {
    const { controller, mockFetch, sleeps } = setup()
    controller.setSendDelays('search', [10, 20])
    controller.setScopeDelay('search', 5)

    const scenario = findSearch(SEARCH_SCENARIO)
    for (let i = 0; i < 3; i += 1) {
      const response = await postJson(
        mockFetch,
        '/search',
        searchBody(scenario, { request_state_id: `state-queue-${i}` }),
      )
      expect(response.status).toBe(200)
    }

    expect(sleeps).toEqual([10, 20, 5])
    expect(controller.getPendingSendDelays('search')).toEqual([])
  })

  it('scope-задержки не смешиваются: facet-очередь не трогает таблицу', async () => {
    const { controller, mockFetch, sleeps } = setup()
    controller.setSendDelays('facet', [30])
    controller.setSendDelays('search', [0])

    await postJson(mockFetch, '/search', searchBody(findSearch(SEARCH_SCENARIO)))
    await postJson(mockFetch, '/search/facet', facetBody(findFacet(FACET_SCENARIO)))

    expect(sleeps).toEqual([30])
    expect(controller.getPendingSendDelays('search')).toEqual([])
    expect(controller.getPendingSendDelays('facet')).toEqual([])
  })
})

describe('управляемые объявленные ошибки searchFiles', () => {
  it.each(declaredCodes)(
    '%s: failNext возвращает контрактную ошибку без правдоподобного успеха',
    async (code) => {
      const { controller, mockFetch } = setup()
      controller.failNext('searchFiles', code)

      const response = await postJson(
        mockFetch,
        '/search',
        searchBody(findSearch(SEARCH_SCENARIO), {
          request_state_id: `state-error-${code.replace(/_/g, '-')}`,
        }),
      )

      const spec = declaredSearchErrors[code]
      expect(response.ok).toBe(false)
      expect(response.status).toBe(spec.status)
      const error = await readError(response)
      expect(error.error.code).toBe(code)
      expect(error.error.retryable).toBe(spec.retryable)
      expect(error.error.request_id).toBe(response.headers.get('X-Request-ID'))
      expect(validateSchema('ErrorResponse', error).valid).toBe(true)
    },
  )

  it('failNext одноразовый: следующая отправка снова успешна', async () => {
    const { controller, mockFetch } = setup()
    controller.failNext('searchFiles', 'SEARCH_UNAVAILABLE')
    const scenario = findSearch(SEARCH_SCENARIO)

    const failed = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-failnext-1' }),
    )
    const succeeded = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-failnext-2' }),
    )

    expect(failed.status).toBe(503)
    expect((await readError(failed)).error.code).toBe('SEARCH_UNAVAILABLE')
    expect(succeeded.status).toBe(200)
    expect(((await succeeded.json()) as { request_state_id: string }).request_state_id).toBe(
      'state-failnext-2',
    )
  })

  it('setError держится до clearError и снимается reset()', async () => {
    const { controller, mockFetch } = setup()
    controller.setError('searchFiles', 'SCHEMA_VERSION_CHANGED')
    const scenario = findSearch(SEARCH_SCENARIO)

    for (const state of ['state-persistent-1', 'state-persistent-2']) {
      const response = await postJson(
        mockFetch,
        '/search',
        searchBody(scenario, { request_state_id: state }),
      )
      expect(response.status).toBe(409)
      expect((await readError(response)).error.code).toBe(
        'SCHEMA_VERSION_CHANGED',
      )
    }

    controller.clearError('searchFiles')
    const cleared = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-persistent-3' }),
    )
    expect(cleared.status).toBe(200)

    controller.setError('searchFiles', 'ROOT_NOT_READY')
    controller.reset()
    controller.setSession(getExample<Session>('auth-session-worker-one'))
    const afterReset = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-persistent-4' }),
    )
    expect(afterReset.status).toBe(200)
  })

  it('ошибки scope не смешиваются: facet-ошибка не влияет на таблицу', async () => {
    const { controller, mockFetch } = setup()
    controller.setError('getSearchFacet', 'SEARCH_UNAVAILABLE')

    const search = await postJson(
      mockFetch,
      '/search',
      searchBody(findSearch(SEARCH_SCENARIO)),
    )
    const facet = await postJson(
      mockFetch,
      '/search/facet',
      facetBody(findFacet(FACET_SCENARIO)),
    )

    expect(search.status).toBe(200)
    expect(facet.status).toBe(503)
    expect((await readError(facet)).error.code).toBe('SEARCH_UNAVAILABLE')
  })

  it('facet воспроизводит каждую объявленную ошибку', async () => {
    for (const code of declaredCodes) {
      const { controller, mockFetch } = setup()
      controller.failNext('getSearchFacet', code)

      const response = await postJson(
        mockFetch,
        '/search/facet',
        facetBody(findFacet(FACET_SCENARIO), {
          request_state_id: `state-facet-error-${code.replace(/_/g, '-')}`,
        }),
      )

      expect(response.status).toBe(declaredSearchErrors[code].status)
      expect((await readError(response)).error.code).toBe(code)
    }
  })
})

describe('invalid request по-прежнему без успеха', () => {
  it('невалидное тело → 422 VALIDATION_ERROR даже при включённой ошибке', async () => {
    const { controller, mockFetch } = setup()
    controller.failNext('searchFiles', 'SEARCH_UNAVAILABLE')
    const body = {
      ...searchBody(findSearch(SEARCH_SCENARIO)),
    } as Record<string, unknown>
    delete body.root_id

    const response = await postJson(mockFetch, '/search', body)

    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.map((item) => item.field)).toContain(
      'root_id',
    )
  })

  it('валидный, но не объявленный запрос → 400 INVALID_QUERY', async () => {
    const { mockFetch } = setup()
    const body: SearchRequest = {
      request_state_id: 'state-unknown-search',
      root_id: 'root-demo-atlas',
      schema_set_version: 'schema-demo-1',
      selected_marker_ids: [],
      query_text: 'archive',
      sort: { field: 'RELEVANCE', direction: 'DESC' },
      facet_prefix: '',
    }

    const response = await postJson(mockFetch, '/search', body)

    expect(response.status).toBe(400)
    expect((await readError(response)).error.code).toBe('INVALID_QUERY')
  })
})

describe('race: детерминированный порядок и точный request_state_id', () => {
  it('обратный порядок задержек разрешает вторую отправку первой', async () => {
    const clock = new ManualClock()
    const { controller, mockFetch } = setup(clock.sleep)
    controller.setSendDelays('search', [30, 0])
    const scenario = findSearch(SEARCH_SCENARIO)
    const order: string[] = []

    const first = postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-race-table-a' }),
    ).then((response) => {
      order.push('A')
      return response
    })
    const second = postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-race-table-b' }),
    ).then((response) => {
      order.push('B')
      return response
    })

    await clock.waitUntil(() => order.includes('B') && clock.pendingCount === 1)
    await clock.advance(30)

    const [a, b] = await Promise.all([first, second])
    expect(order).toEqual(['B', 'A'])
    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    expect(((await a.json()) as { request_state_id: string }).request_state_id).toBe(
      'state-race-table-a',
    )
    expect(((await b.json()) as { request_state_id: string }).request_state_id).toBe(
      'state-race-table-b',
    )
  })

  it('поздний facet не подменяет table-ответ и имеет свой request_state_id', async () => {
    const clock = new ManualClock()
    const { controller, mockFetch } = setup(clock.sleep)
    controller.setSendDelays('search', [0])
    controller.setSendDelays('facet', [30])
    const order: string[] = []

    const tablePromise = postJson(
      mockFetch,
      '/search',
      searchBody(findSearch(SEARCH_SCENARIO), {
        request_state_id: 'state-race-table-x',
      }),
    ).then((response) => {
      order.push('table')
      return response
    })
    const facetPromise = postJson(
      mockFetch,
      '/search/facet',
      facetBody(findFacet(FACET_SCENARIO), {
        request_state_id: 'state-race-level-y',
      }),
    ).then((response) => {
      order.push('facet')
      return response
    })

    await clock.waitUntil(() => order.includes('table') && clock.pendingCount === 1)
    const table = await tablePromise
    expect(table.status).toBe(200)
    expect(order).toEqual(['table'])

    await clock.advance(30)
    const facet = await facetPromise

    expect(order).toEqual(['table', 'facet'])
    expect(facet.status).toBe(200)
    expect(((await table.json()) as { request_state_id: string }).request_state_id).toBe(
      'state-race-table-x',
    )
    expect(
      ((await facet.json()) as { request_state_id: string }).request_state_id,
    ).toBe('state-race-level-y')
  })

  it('level-list race: обратный порядок задержек сохраняет свой request_state_id', async () => {
    const clock = new ManualClock()
    const { controller, mockFetch } = setup(clock.sleep)
    controller.setSendDelays('facet', [30, 0])
    const scenario = findFacet(FACET_SCENARIO)
    const order: string[] = []

    const first = postJson(
      mockFetch,
      '/search/facet',
      facetBody(scenario, { request_state_id: 'state-race-level-a' }),
    ).then((response) => {
      order.push('A')
      return response
    })
    const second = postJson(
      mockFetch,
      '/search/facet',
      facetBody(scenario, { request_state_id: 'state-race-level-b' }),
    ).then((response) => {
      order.push('B')
      return response
    })

    await clock.waitUntil(() => order.includes('B') && clock.pendingCount === 1)
    await clock.advance(30)

    const [a, b] = await Promise.all([first, second])
    expect(order).toEqual(['B', 'A'])
    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    expect(
      ((await a.json()) as { request_state_id: string }).request_state_id,
    ).toBe('state-race-level-a')
    expect(
      ((await b.json()) as { request_state_id: string }).request_state_id,
    ).toBe('state-race-level-b')
  })

  it('разрешённый повтор после ошибки получает новый request_state_id', async () => {
    const { controller, mockFetch } = setup()
    const scenario = findSearch(SEARCH_SCENARIO)
    controller.failNext('searchFiles', 'INVALID_QUERY')

    const first = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-retry-a' }),
    )
    const second = await postJson(
      mockFetch,
      '/search',
      searchBody(scenario, { request_state_id: 'state-retry-b' }),
    )

    expect(first.status).toBe(400)
    expect((await readError(first)).error.code).toBe('INVALID_QUERY')
    expect(second.status).toBe(200)
    expect(
      ((await second.json()) as { request_state_id: string }).request_state_id,
    ).toBe('state-retry-b')
  })

  it('reset() снимает задержки, очереди и ошибки', async () => {
    const { controller, mockFetch, sleeps } = setup()
    controller.setScopeDelay('search', 15)
    controller.setScopeDelay('facet', 25)
    controller.setSendDelays('search', [10])
    controller.failNext('searchFiles', 'INTERNAL_ERROR')
    controller.setError('getSearchFacet', 'RATE_LIMITED')

    controller.reset()
    controller.setSession(getExample<Session>('auth-session-worker-one'))

    const search = await postJson(
      mockFetch,
      '/search',
      searchBody(findSearch(SEARCH_SCENARIO), {
        request_state_id: 'state-after-reset',
      }),
    )
    const facet = await postJson(
      mockFetch,
      '/search/facet',
      facetBody(findFacet(FACET_SCENARIO)),
    )

    expect(search.status).toBe(200)
    expect(facet.status).toBe(200)
    expect(sleeps).toEqual([])
    expect(controller.getScopeDelay('search')).toBe(0)
    expect(controller.getScopeDelay('facet')).toBe(0)
    expect(controller.getPendingSendDelays('search')).toEqual([])
    expect(controller.getPendingSendDelays('facet')).toEqual([])
  })
})

describe('503 через транспорт с retry.maxAttempts=1', () => {
  it('не превращается в успех', async () => {
    const controller = new MockController({ sleep: async () => {} })
    const mockFetch = createMockFetch(controller)
    const api = createApiClient({
      mode: 'mock',
      baseUrl: 'http://localhost/api/v1',
      fetch: mockFetch,
      retry: { maxAttempts: 1 },
      sleep: async () => {},
    })
    const login = getExample<LoginRequest>('auth-login-request-worker-one')
    const loginResult = await api.POST('/auth/login', { body: login })
    expect(loginResult.response.status).toBe(200)

    controller.failNext('searchFiles', 'SEARCH_UNAVAILABLE')
    const result = await api.POST('/search', {
      body: searchBody(findSearch(SEARCH_SCENARIO), {
        request_state_id: 'state-503-retry',
      }),
    })

    expect(result.response.status).toBe(503)
    expect(result.error?.error.code).toBe('SEARCH_UNAVAILABLE')
    expect(result.data).toBeUndefined()
  })
})
