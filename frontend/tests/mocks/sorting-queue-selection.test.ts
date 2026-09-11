// LT-07.2a: контрактные mocks очереди и выбора
// (`querySortingQueue`/`createSortingSelection`) без matcher, readiness- и
// snapshot-алгоритма.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую для
// невалидных запросов, которые типизированный клиент не позволяет собрать.
// Все успешные ответы дополнительно валидируются по схемам OAS.
//
// Очередь отдаёт literal canned `QueueResponse` выбранного контроллером
// сценария (0/120/1001, все активные 0/120, MISSING, query_text); объявлена
// только первая страница, поэтому непустой cursor → 422. Выбор EXPLICIT/ALL_
// MATCHING сверяет `expected_eligible_count` с canned eligible_count и создаёт
// неизменяемый снимок; owner/expiry/unknown снимка объявлены для preview/batch
// и воспроизводятся резолвером store (не create-операцией).

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  createMockFetch,
  MockController,
  type MockFetch,
  type QueueScenario,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import {
  MAX_BATCH_ITEMS,
  declaredSortingErrors,
  isSortingErrorDeclaredForOperation,
  selectionUseErrorResponse,
  sortingErrorCodesByOperation,
} from '@/mocks'
import type { MockSortingErrorCode, MockSortingOperation } from '@/mocks'
import type {
  ErrorResponse,
  LoginRequest,
  QueueQueryRequest,
  QueueResponse,
  SelectionRequest,
  SelectionSnapshot,
  Session,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
}

function setup(): Setup {
  const controller = new MockController({ sleep: async () => {} })
  const mockFetch = createMockFetch(controller)
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
    // Читающий POST очереди может повторяться на 429/503; в тестах ошибок
    // фиксируем одну попытку, чтобы наблюдать именно объявленный ответ.
    retry: { maxAttempts: 1 },
  })
  return { controller, mockFetch, api }
}

function request(path: string, init?: RequestInit): Request {
  return new Request(`http://localhost/api/v1${path}`, init)
}

async function readError(response: Response): Promise<ErrorResponse> {
  return (await response.json()) as ErrorResponse
}

async function loginAs(
  api: WiseWayApiClient,
  exampleId: string,
): Promise<Session> {
  const body = getExample<LoginRequest>(exampleId)
  const result = await api.POST('/auth/login', { body })
  expect(result.response.status).toBe(200)
  if (!result.data) {
    throw new Error(`login ${exampleId} не вернул Session`)
  }
  return result.data
}

async function loginWorkerOne(api: WiseWayApiClient): Promise<Session> {
  return loginAs(api, 'auth-login-request-worker-one')
}

/** Логин и установка CSRF-токена в session-context (как реальный UI). */
async function loginWithCsrf(
  api: WiseWayApiClient,
  exampleId = 'auth-login-request-worker-one',
): Promise<Session> {
  const session = await loginAs(api, exampleId)
  setCsrfToken(session.csrf_token)
  return session
}

function expectSchema(schemaName: string, value: unknown): void {
  expect(validateSchema(schemaName, value).valid, schemaName).toBe(true)
}

const ATLAS = 'company-demo-atlas'

function queueBody(
  overrides: Partial<QueueQueryRequest> = {},
): QueueQueryRequest {
  return {
    company_id: ATLAS,
    filters: { statuses: [], query_text: '' },
    cursor: null,
    limit: 100,
    ...overrides,
  }
}

/** Запрос, соответствующий canned-сценарию `ready-120`. */
function readyQueueBody(): QueueQueryRequest {
  return queueBody({ filters: { statuses: ['READY'], query_text: '' } })
}

function postQueue(api: WiseWayApiClient, body: QueueQueryRequest) {
  return api.POST('/sorting/queue/query', { body })
}

function postSelection(api: WiseWayApiClient, body: SelectionRequest) {
  return api.POST('/sorting/selections', {
    params: { header: { 'X-CSRF-Token': 'caller-placeholder' } },
    body,
  })
}

const EXPLICIT_ONE: SelectionRequest = {
  company_id: ATLAS,
  mode: 'EXPLICIT',
  items: [{ item_id: 'queue-atlas-ready-0001', item_revision: 1 }],
}

const EXPLICIT_MULTIPLE: SelectionRequest = {
  company_id: ATLAS,
  mode: 'EXPLICIT',
  items: [
    { item_id: 'queue-atlas-ready-0001', item_revision: 1 },
    { item_id: 'queue-atlas-ready-0101', item_revision: 1 },
    { item_id: 'queue-atlas-ready-0120', item_revision: 1 },
  ],
}

function allMatching(
  expected: number,
  statuses: QueueQueryRequest['filters']['statuses'] = ['READY'],
): SelectionRequest {
  return {
    company_id: ATLAS,
    mode: 'ALL_MATCHING',
    filters: { statuses, query_text: '' },
    expected_eligible_count: expected,
  }
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация очереди/выбора', () => {
  it('регистрирует 2 операции', () => {
    expect(matchMockRoute('POST', '/sorting/queue/query')).toBeDefined()
    expect(matchMockRoute('POST', '/sorting/selections')).toBeDefined()
    expect(matchMockRoute('POST', '/sorting/queue/query')?.params).toEqual({})
    expect(matchMockRoute('POST', '/sorting/selections')?.params).toEqual({})
  })

  it('успешные ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const queue = await postQueue(api, readyQueueBody())
    expect(queue.response.status).toBe(200)
    expect(queue.response.headers.get('Cache-Control')).toBe('no-store')
    expect(queue.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )

    const selection = await postSelection(api, EXPLICIT_ONE)
    expect(selection.response.status).toBe(201)
    expect(selection.response.headers.get('X-WiseWay-Mock')).toBe('mock')
  })
})

describe('mock queue: literal canned-сценарии', () => {
  const cases: Array<{
    scenario: QueueScenario
    exampleId: string
    statuses: QueueQueryRequest['filters']['statuses']
    queryText?: string
  }> = [
    {
      scenario: 'ready-120',
      exampleId: 'queue-ready-120-page1',
      statuses: ['READY'],
    },
    { scenario: 'ready-0', exampleId: 'queue-ready-0', statuses: ['READY'] },
    {
      scenario: 'ready-1001',
      exampleId: 'queue-ready-1001-page1',
      statuses: ['READY'],
    },
    {
      scenario: 'all-active-120',
      exampleId: 'queue-all-active-120',
      statuses: [],
    },
    { scenario: 'all-active-0', exampleId: 'queue-all-active-0', statuses: [] },
    {
      scenario: 'missing-explicit',
      exampleId: 'queue-missing-explicit',
      statuses: ['MISSING'],
    },
    {
      scenario: 'query-text',
      exampleId: 'queue-query-text',
      statuses: ['READY'],
      queryText: 'report-0001',
    },
  ]

  for (const { scenario, exampleId, statuses, queryText } of cases) {
    it(`${scenario}: 200 literal ${exampleId} и schema-valid`, async () => {
      const { api, controller } = setup()
      await loginWorkerOne(api)
      controller.setQueueScenario(scenario)

      const result = await postQueue(
        api,
        queueBody({
          filters: { statuses, query_text: queryText ?? '' },
        }),
      )
      expect(result.response.status).toBe(200)
      expect(result.data).toEqual(getExample<QueueResponse>(exampleId))
      expectSchema('QueueResponse', result.data)
    })
  }

  it('фильтры, не соответствующие сценарию, → 422 без правдоподобного успеха', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const result = await postQueue(
      api,
      queueBody({ filters: { statuses: [], query_text: '' } }),
    )
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('VALIDATION_ERROR')
    expect(result.data).toBeUndefined()
  })

  it('ready-120: literal counters/status_counts/generation/next_cursor', async () => {
    const { api } = setup()
    await loginWorkerOne(api)

    const result = await postQueue(
      api,
      queueBody({ filters: { statuses: ['READY'], query_text: '' } }),
    )
    expect(result.response.status).toBe(200)
    const data = result.data as QueueResponse
    expect(data.queue_generation).toBe('queue-generation-atlas-120')
    expect(data.matching_count).toBe(120)
    expect(data.eligible_count).toBe(120)
    expect(data.counters).toEqual({ ready: 120, processing: 2, attention: 3 })
    expect(data.status_counts).toContainEqual({ status: 'READY', count: 120 })
    expect(data.next_cursor).toBe('cursor-atlas-ready-0101')
    expect(data.items).toHaveLength(100)
  })

  it('ready-0: пустая страница, нулевые счётчики, next_cursor=null', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setQueueScenario('ready-0')

    const result = await postQueue(
      api,
      queueBody({ filters: { statuses: ['READY'], query_text: '' } }),
    )
    const data = result.data as QueueResponse
    expect(data.items).toEqual([])
    expect(data.matching_count).toBe(0)
    expect(data.eligible_count).toBe(0)
    expect(data.counters.ready).toBe(0)
    expect(data.next_cursor).toBeNull()
  })

  it('ready-1001: страница capped на 100, eligible 1001', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setQueueScenario('ready-1001')

    const result = await postQueue(
      api,
      queueBody({ filters: { statuses: ['READY'], query_text: '' } }),
    )
    const data = result.data as QueueResponse
    expect(data.matching_count).toBe(1001)
    expect(data.eligible_count).toBe(1001)
    expect(data.counters.ready).toBe(1001)
    expect(data.items).toHaveLength(100)
    expect(data.next_cursor).toBe('cursor-atlas-limit-0101')
  })

  it('all-active-0: непустая очередь без selectable, eligible 0', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setQueueScenario('all-active-0')

    const result = await postQueue(api, queueBody())
    const data = result.data as QueueResponse
    expect(data.matching_count).toBe(3)
    expect(data.eligible_count).toBe(0)
    expect(data.counters).toEqual({ ready: 0, processing: 0, attention: 0 })
    expect(data.items.every((item) => !item.selectable)).toBe(true)
  })

  it('missing-explicit: MISSING виден только по явному фильтру и не eligible', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setQueueScenario('missing-explicit')

    const result = await postQueue(
      api,
      queueBody({ filters: { statuses: ['MISSING'], query_text: '' } }),
    )
    const data = result.data as QueueResponse
    expect(data.status_counts).toContainEqual({ status: 'MISSING', count: 2 })
    expect(data.eligible_count).toBe(0)
    expect(data.items.every((item) => item.status === 'MISSING')).toBe(true)
  })

  it('query-text: literal подстрочный фильтр по имени', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setQueueScenario('query-text')

    const result = await postQueue(
      api,
      queueBody({
        filters: { statuses: ['READY'], query_text: 'report-0001' },
      }),
    )
    const data = result.data as QueueResponse
    expect(data.matching_count).toBe(1)
    expect(data.eligible_count).toBe(1)
    expect(data.items).toHaveLength(1)
    expect(data.items[0].item_id).toBe('queue-atlas-ready-0001')
  })

  it('cursor/limit: непустой курсор и невалидный limit → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    await loginWorkerOne(api)

    const declaredCursor = await postQueue(
      api,
      queueBody({ cursor: 'cursor-atlas-ready-0101' }),
    )
    expect(declaredCursor.response.status).toBe(422)
    expect(declaredCursor.error?.error.code).toBe('VALIDATION_ERROR')

    const badLimit = await mockFetch(
      request('/sorting/queue/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queueBody({ limit: 0 })),
      }),
    )
    expect(badLimit.status).toBe(422)
    expect((await readError(badLimit)).error.code).toBe('VALIDATION_ERROR')

    const tooBig = await mockFetch(
      request('/sorting/queue/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queueBody({ limit: 101 })),
      }),
    )
    expect(tooBig.status).toBe(422)
  })
})

describe('mock selection: EXPLICIT', () => {
  it('один элемент → 201 literal explicit-one и запись в store', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, EXPLICIT_ONE)
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<SelectionSnapshot>('selection-snapshot-explicit-one'),
    )
    expectSchema('SelectionSnapshot', result.data)

    const stored = controller
      .getSelectionStore()
      .get('selection-atlas-explicit-one')
    expect(stored?.members).toEqual([
      { item_id: 'queue-atlas-ready-0001', item_revision: 1 },
    ])
    expect(stored?.snapshot.selected_count).toBe(1)
  })

  it('несколько элементов → 201 literal explicit-multiple, selected_count=3', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, EXPLICIT_MULTIPLE)
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<SelectionSnapshot>('selection-snapshot-explicit-multiple'),
    )
    const stored = controller
      .getSelectionStore()
      .get('selection-atlas-explicit-multiple')
    expect(stored?.members).toHaveLength(3)
    expect(stored?.snapshot.selected_count).toBe(3)
  })

  it('два элемента → multiple canned с selected_count=2', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, {
      company_id: ATLAS,
      mode: 'EXPLICIT',
      items: [
        { item_id: 'queue-atlas-ready-0001', item_revision: 1 },
        { item_id: 'queue-atlas-ready-0002', item_revision: 1 },
      ],
    })
    expect(result.response.status).toBe(201)
    expect(result.data?.selected_count).toBe(2)
    expect(result.data?.selection_id).toBe('selection-atlas-explicit-multiple')
  })
})

describe('mock selection: ALL_MATCHING', () => {
  it('ready-120, expected 120 → 201 literal all-matching-120', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, allMatching(120))
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<SelectionSnapshot>('selection-snapshot-all-matching-120'),
    )
    expectSchema('SelectionSnapshot', result.data)
  })

  it('0 eligible → 422 EMPTY_SELECTION, снимок не создан', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setQueueScenario('ready-0')

    const result = await postSelection(api, allMatching(0))
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('EMPTY_SELECTION')
    expectSchema('ErrorResponse', result.error)
    expect(controller.getSelectionStore().list()).toHaveLength(0)
  })

  it('1001 eligible → 422 BATCH_LIMIT_EXCEEDED без усечения и снимка', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setQueueScenario('ready-1001')

    const result = await postSelection(api, allMatching(1001))
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('BATCH_LIMIT_EXCEEDED')
    expect(result.data).toBeUndefined()
    expect(controller.getSelectionStore().list()).toHaveLength(0)
    expect(MAX_BATCH_ITEMS).toBe(1000)
  })

  it('расхождение expected_eligible_count → 409 SELECTION_CHANGED', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, allMatching(119))
    expect(result.response.status).toBe(409)
    expect(result.error?.error.code).toBe('SELECTION_CHANGED')
    expectSchema('ErrorResponse', result.error)
    expect(controller.getSelectionStore().list()).toHaveLength(0)
  })

  it('eligibleCountOverride воспроизводит count change', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setEligibleCountOverride(119)

    const result = await postSelection(api, allMatching(120))
    expect(result.response.status).toBe(409)
    expect(result.error?.error.code).toBe('SELECTION_CHANGED')
  })

  it('all-active-120, expected 121 → 201 с generation сценария', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setQueueScenario('all-active-120')

    const result = await postSelection(api, allMatching(121, []))
    expect(result.response.status).toBe(201)
    expect(result.data?.selected_count).toBe(121)
    expect(result.data?.queue_generation).toBe(
      'queue-generation-atlas-120',
    )
  })

  it('ALL_MATCHING с фильтрами вне сценария → 422 без успеха', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await postSelection(api, allMatching(120, []))
    expect(result.response.status).toBe(422)
    expect(result.error?.error.code).toBe('VALIDATION_ERROR')
  })
})

describe('mock selection: поздние поступления не меняют снимок', () => {
  it('смена queue-сценария/eligible после создания не меняет снимок', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    const created = await postSelection(api, allMatching(120))
    expect(created.response.status).toBe(201)
    const selectionId = created.data?.selection_id ?? ''

    // Позднее поступление: другой сценарий и переопределённый eligible.
    controller.setQueueScenario('ready-1001')
    controller.setEligibleCountOverride(121)

    const stored = controller.getSelectionStore().get(selectionId)
    expect(stored?.snapshot.selected_count).toBe(120)
    expect(stored?.snapshot).toEqual(created.data)
    expect(controller.getSelectionStore().list()).toHaveLength(1)
  })
})

describe('mock selection: owner/expiry/unknown снимка (preview/batch semantics)', () => {
  it('владелец — found; другой пользователь — forbidden (403 FORBIDDEN)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api, 'auth-login-request-worker-one')
    const created = await postSelection(api, EXPLICIT_ONE)
    const selectionId = created.data?.selection_id ?? ''

    const ownerId = controller.getSession()?.actor.user_id ?? ''
    expect(
      controller.getSelectionStore().resolve(selectionId, {
        actorId: ownerId,
        now: null,
      }).kind,
    ).toBe('found')

    const forbidden = controller.getSelectionStore().resolve(selectionId, {
      actorId: 'user-demo-worker-2',
      now: null,
    })
    expect(forbidden.kind).toBe('forbidden')

    const response = selectionUseErrorResponse('request-mock-1', 'FORBIDDEN')
    expect(response.status).toBe(403)
    expect((await readError(response)).error.code).toBe('FORBIDDEN')
  })

  it('истёкший снимок → expired (409 SELECTION_EXPIRED)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    const created = await postSelection(api, EXPLICIT_ONE)
    const selectionId = created.data?.selection_id ?? ''
    const ownerId = controller.getSession()?.actor.user_id ?? ''

    const active = controller.getSelectionStore().resolve(selectionId, {
      actorId: ownerId,
      now: '2031-05-10T09:35:00Z',
    })
    expect(active.kind).toBe('found')

    const expired = controller.getSelectionStore().resolve(selectionId, {
      actorId: ownerId,
      now: '2031-05-10T09:36:00Z',
    })
    expect(expired.kind).toBe('expired')

    const response = selectionUseErrorResponse(
      'request-mock-2',
      'SELECTION_EXPIRED',
    )
    expect(response.status).toBe(409)
    expect((await readError(response)).error.code).toBe('SELECTION_EXPIRED')
  })

  it('неизвестный снимок → not_found (404 NOT_FOUND)', async () => {
    const { controller } = setup()
    expect(
      controller.getSelectionStore().resolve('selection-unknown', {
        actorId: 'user-demo-worker-1',
        now: null,
      }).kind,
    ).toBe('not_found')

    const response = selectionUseErrorResponse('request-mock-3', 'NOT_FOUND')
    expect(response.status).toBe(404)
    expect((await readError(response)).error.code).toBe('NOT_FOUND')
  })

  it('create не возвращает необъявленные 404/SELECTION_EXPIRED', () => {
    expect(
      Object.prototype.hasOwnProperty.call(
        declaredSortingErrors,
        'SELECTION_EXPIRED',
      ),
    ).toBe(false)
    expect(
      Object.prototype.hasOwnProperty.call(declaredSortingErrors, 'NOT_FOUND'),
    ).toBe(false)
  })
})

describe('mock queue/selection: 401/403/404/422', () => {
  it('без сессии → 401 (queue и selection)', async () => {
    const { api } = setup()

    const queue = await postQueue(api, readyQueueBody())
    expect(queue.response.status).toBe(401)
    expect(queue.error?.error.code).toBe('UNAUTHENTICATED')

    const selection = await postSelection(api, EXPLICIT_ONE)
    expect(selection.response.status).toBe(401)
    expect(selection.error?.error.code).toBe('UNAUTHENTICATED')
  })

  it('selection без/с неверным CSRF → 403, store не меняется', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)

    const noToken = await postSelection(api, EXPLICIT_ONE)
    expect(noToken.response.status).toBe(403)
    expect(noToken.error?.error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrong = await postSelection(api, EXPLICIT_ONE)
    expect(wrong.response.status).toBe(403)
    expect(controller.getSelectionStore().list()).toHaveLength(0)
  })

  it('неизвестный маршрут → 404 NOT_FOUND', async () => {
    const { mockFetch } = setup()
    const response = await mockFetch(
      request('/sorting/previews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selection_id: 'selection-unknown' }),
      }),
    )
    expect(response.status).toBe(404)
    expect((await readError(response)).error.code).toBe('NOT_FOUND')
  })

  it('invalid body → 422 без успеха (queue и selection)', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    // queue: отсутствует company_id.
    const queueMissing = await mockFetch(
      request('/sorting/queue/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: { statuses: ['READY'], query_text: '' },
          cursor: null,
          limit: 100,
        }),
      }),
    )
    expect(queueMissing.status).toBe(422)
    expect((await readError(queueMissing)).error.code).toBe('VALIDATION_ERROR')

    // selection: неизвестный mode (oneOf).
    const unknownMode = await mockFetch(
      request('/sorting/selections', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({
          company_id: ATLAS,
          mode: 'SELECT_ALL',
          items: [{ item_id: 'queue-atlas-ready-0001', item_revision: 1 }],
        }),
      }),
    )
    expect(unknownMode.status).toBe(422)

    // selection: пустой EXPLICIT items (minItems 1).
    const emptyItems = await mockFetch(
      request('/sorting/selections', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({
          company_id: ATLAS,
          mode: 'EXPLICIT',
          items: [],
        }),
      }),
    )
    expect(emptyItems.status).toBe(422)

    // selection: лишнее свойство (additionalProperties=false).
    const extra = await mockFetch(
      request('/sorting/selections', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({ ...allMatching(120), page_item_ids: ['x'] }),
      }),
    )
    expect(extra.status).toBe(422)
  })
})

describe('mock queue/selection: управляемые ошибки и reset', () => {
  it('failNext очереди расходуется один раз (объявленный код)', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.failNext('querySortingQueue', 'RATE_LIMITED')

    const first = await postQueue(api, readyQueueBody())
    expect(first.response.status).toBe(429)
    expect(first.error?.error.code).toBe('RATE_LIMITED')

    const second = await postQueue(api, readyQueueBody())
    expect(second.response.status).toBe(200)
  })

  it('setError выбора использует объявленный код и clearError снимает его', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setError('createSortingSelection', 'FORBIDDEN')

    const forced = await postSelection(api, EXPLICIT_ONE)
    expect(forced.response.status).toBe(403)
    expect(forced.error?.error.code).toBe('FORBIDDEN')

    controller.clearError('createSortingSelection')
    const normal = await postSelection(api, EXPLICIT_ONE)
    expect(normal.response.status).toBe(201)
  })

  it('503 обеих операций → SERVICE_UNAVAILABLE, никогда SEARCH_UNAVAILABLE', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    controller.setError('querySortingQueue', 'SERVICE_UNAVAILABLE')
    const queue = await postQueue(api, readyQueueBody())
    expect(queue.response.status).toBe(503)
    expect(queue.error?.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(queue.error?.error.code).not.toBe('SEARCH_UNAVAILABLE')
    expect(queue.error?.error.retryable).toBe(true)
    expect(queue.error?.error.operation_id).toBeNull()
    expect(queue.error?.error.field_errors).toEqual([])
    expectSchema('ErrorResponse', queue.error)

    controller.clearError('querySortingQueue')
    controller.setError('createSortingSelection', 'SERVICE_UNAVAILABLE')
    const selection = await postSelection(api, EXPLICIT_ONE)
    expect(selection.response.status).toBe(503)
    expect(selection.error?.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(selection.error?.error.code).not.toBe('SEARCH_UNAVAILABLE')
    expect(selection.error?.error.retryable).toBe(true)
    expect(selection.error?.error.operation_id).toBeNull()
    expect(selection.error?.error.field_errors).toEqual([])
    expectSchema('ErrorResponse', selection.error)

    // SEARCH_UNAVAILABLE не входит ни в один sorting-набор.
    expect(declaredSortingErrors).not.toHaveProperty('SEARCH_UNAVAILABLE')
    for (const codes of Object.values(sortingErrorCodesByOperation)) {
      expect(codes).not.toContain('SEARCH_UNAVAILABLE')
    }
  })

  it('per-operation ограничение: коды другой операции отклоняются (типы + runtime)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)

    // Компиляция: overload'ы не принимают код другой операции.
    // @ts-expect-error SELECTION_CHANGED не объявлен для querySortingQueue
    controller.setError('querySortingQueue', 'SELECTION_CHANGED')
    // @ts-expect-error EMPTY_SELECTION не объявлен для querySortingQueue
    controller.failNext('querySortingQueue', 'EMPTY_SELECTION')
    // @ts-expect-error SELECTION_EXPIRED не объявлен для createSortingSelection
    controller.setError('createSortingSelection', 'SELECTION_EXPIRED')

    // Runtime: даже обход типов не даёт undeclared HTTP-статус.
    const rawSetError = controller.setError as unknown as (
      operation: MockSortingOperation,
      code: MockSortingErrorCode,
    ) => void
    const rawFailNext = controller.failNext as unknown as (
      operation: MockSortingOperation,
      code: MockSortingErrorCode,
    ) => void
    // SELECTION_EXPIRED не входит даже в sorting-union (объявлен только для
    // preview/batch) — проверяем runtime-guard через полный обход типов.
    const rawSetErrorAny = controller.setError as unknown as (
      operation: string,
      code: string,
    ) => void
    rawSetError('querySortingQueue', 'SELECTION_CHANGED')
    rawFailNext('querySortingQueue', 'BATCH_LIMIT_EXCEEDED')
    rawSetErrorAny('createSortingSelection', 'SELECTION_EXPIRED')

    const queue = await postQueue(api, readyQueueBody())
    expect(queue.response.status).toBe(200)

    const selection = await postSelection(api, EXPLICIT_ONE)
    expect(selection.response.status).toBe(201)

    // Явная проверка per-operation набора.
    expect(
      isSortingErrorDeclaredForOperation(
        'querySortingQueue',
        'SELECTION_CHANGED',
      ),
    ).toBe(false)
    expect(
      isSortingErrorDeclaredForOperation(
        'querySortingQueue',
        'EMPTY_SELECTION',
      ),
    ).toBe(false)
    expect(
      isSortingErrorDeclaredForOperation(
        'createSortingSelection',
        'SELECTION_CHANGED',
      ),
    ).toBe(true)
    expect(
      isSortingErrorDeclaredForOperation(
        'createSortingSelection',
        'EMPTY_SELECTION',
      ),
    ).toBe(true)
    expect(sortingErrorCodesByOperation.querySortingQueue).toEqual([
      'UNAUTHENTICATED',
      'FORBIDDEN',
      'VALIDATION_ERROR',
      'RATE_LIMITED',
      'INTERNAL_ERROR',
      'SERVICE_UNAVAILABLE',
    ])
  })

  it('reset восстанавливает сценарий/override/store и очищает ошибки', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    controller.setQueueScenario('ready-1001')
    controller.setEligibleCountOverride(5)
    controller.setSelectionNow('2031-05-10T10:00:00Z')
    controller.failNext('querySortingQueue', 'INTERNAL_ERROR')
    await postSelection(api, EXPLICIT_ONE)
    expect(controller.getSelectionStore().list()).toHaveLength(1)

    controller.reset()

    expect(controller.getQueueScenario()).toBe('ready-120')
    expect(controller.getEligibleCountOverride()).toBeNull()
    expect(controller.getSelectionNow()).toBeNull()
    expect(controller.getSelectionStore().list()).toHaveLength(0)

    resetSessionContext()
    await loginWorkerOne(api)
    const result = await postQueue(api, readyQueueBody())
    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(
      getExample<QueueResponse>('queue-ready-120-page1'),
    )
  })
})
