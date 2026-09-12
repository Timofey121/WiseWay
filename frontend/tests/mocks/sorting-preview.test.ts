// LT-07.2b: контрактные mocks preview
// (`createSortingPreview`/`getSortingPreview`) без matcher, ranking и файловых
// действий.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую для
// невалидных запросов, которые типизированный клиент не позволяет собрать.
// Все успешные ответы дополнительно валидируются по схемам OAS.
//
// Preview отдаёт literal canned-сценарии из
// `contracts/examples/sorting/preview-*.json`: EXPLICIT one/multiple,
// allmatching-120 page1, hetero (все Prediction/CollisionDetails kinds,
// nullable цели) и conflict (RULE_CONFLICT). Сценарий выбирает контроллер либо
// выводит из разрешённого снимка. Preview не выполняет movement и не создаёт
// batch: проверяется отсутствие POST `/sorting/batches`.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  PREVIEW_SCENARIOS,
  declaredSelectionUseErrors,
  isPreviewErrorCode,
  isSortingErrorDeclaredForOperation,
  selectionUseErrorResponse,
  sortingErrorCodesByOperation,
} from '@/mocks'
import {
  createMockFetch,
  MockController,
  type MockFetch,
  type PreviewScenario,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type { MockSortingErrorCode, MockSortingOperation } from '@/mocks'
import type {
  ErrorResponse,
  LoginRequest,
  Preview,
  SelectionRequest,
  Session,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
  /** Метод и путь каждого реально ушедшего запроса (для проверки movement). */
  calls: string[]
}

function setup(): Setup {
  const controller = new MockController({ sleep: async () => {} })
  const inner = createMockFetch(controller)
  const calls: string[] = []
  const mockFetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    calls.push(
      `${request.method.toUpperCase()} ${new URL(request.url).pathname}`,
    )
    return inner(request)
  }
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
    retry: { maxAttempts: 1 },
  })
  return { controller, mockFetch, api, calls }
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

function allMatching(expected: number): SelectionRequest {
  return {
    company_id: ATLAS,
    mode: 'ALL_MATCHING',
    filters: { statuses: ['READY'], query_text: '' },
    expected_eligible_count: expected,
  }
}

function postSelection(api: WiseWayApiClient, body: SelectionRequest) {
  return api.POST('/sorting/selections', {
    params: { header: { 'X-CSRF-Token': 'caller-placeholder' } },
    body,
  })
}

function postPreview(api: WiseWayApiClient, selectionId: string) {
  return api.POST('/sorting/previews', {
    params: { header: { 'X-CSRF-Token': 'caller-placeholder' } },
    body: { selection_id: selectionId },
  })
}

function getPreview(
  api: WiseWayApiClient,
  previewId: string,
  query?: { cursor?: string; limit?: number },
) {
  return api.GET('/sorting/previews/{preview_id}', {
    params: { path: { preview_id: previewId }, query },
  })
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация preview', () => {
  it('регистрирует createSortingPreview и getSortingPreview', () => {
    const create = matchMockRoute('POST', '/sorting/previews')
    expect(create).toBeDefined()
    expect(create?.params).toEqual({})

    const get = matchMockRoute(
      'GET',
      '/sorting/previews/preview-atlas-explicit-one',
    )
    expect(get).toBeDefined()
    expect(get?.params).toEqual({
      preview_id: 'preview-atlas-explicit-one',
    })
  })

  it('успешные ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)

    const created = await postPreview(api, 'selection-atlas-explicit-one')
    expect(created.response.status).toBe(201)
    expect(created.response.headers.get('Cache-Control')).toBe('no-store')
    expect(created.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
    expect(created.response.headers.get('X-WiseWay-Mock')).toBe('mock')

    const read = await getPreview(api, 'preview-atlas-explicit-one')
    expect(read.response.status).toBe(200)
    expect(read.response.headers.get('X-WiseWay-Mock')).toBe('mock')
  })
})

describe('mock preview: EXPLICIT/ALL_MATCHING canned-сценарии', () => {
  it('EXPLICIT one → 201 literal preview-atlas-explicit-one', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)

    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<Preview>('preview-atlas-explicit-one'),
    )
    expectSchema('Preview', result.data)
    expect(controller.getPreviewStore().get('preview-atlas-explicit-one')).toBeDefined()
  })

  it('EXPLICIT multiple → 201 literal preview-atlas-explicit-multiple', async () => {
    const { api } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_MULTIPLE)

    const result = await postPreview(api, 'selection-atlas-explicit-multiple')
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<Preview>('preview-atlas-explicit-multiple'),
    )
    expectSchema('Preview', result.data)
    expect(result.data?.total).toBe(3)
    expect(result.data?.rows).toHaveLength(3)
  })

  it('ALL_MATCHING 120 → 201 literal page1 (100 rows, непустой cursor)', async () => {
    const { api } = setup()
    await loginWithCsrf(api)
    await postSelection(api, allMatching(120))

    const result = await postPreview(api, 'selection-atlas-allmatching-120')
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<Preview>('preview-atlas-allmatching-120-page1'),
    )
    expectSchema('Preview', result.data)
    expect(result.data?.total).toBe(120)
    expect(result.data?.rows).toHaveLength(100)
    expect(result.data?.next_cursor).toBe(
      'cursor-preview-atlas-allmatching-0101',
    )
  })

  it('сценарий выводится из снимка: EXPLICIT one/multiple, ALL_MATCHING', async () => {
    const one = setup()
    await loginWithCsrf(one.api)
    await postSelection(one.api, EXPLICIT_ONE)
    const oneResult = await postPreview(one.api, 'selection-atlas-explicit-one')
    expect(oneResult.data?.preview_id).toBe('preview-atlas-explicit-one')

    const multiple = setup()
    await loginWithCsrf(multiple.api)
    await postSelection(multiple.api, EXPLICIT_MULTIPLE)
    const multipleResult = await postPreview(
      multiple.api,
      'selection-atlas-explicit-multiple',
    )
    expect(multipleResult.data?.preview_id).toBe(
      'preview-atlas-explicit-multiple',
    )

    const all = setup()
    await loginWithCsrf(all.api)
    await postSelection(all.api, allMatching(120))
    const allResult = await postPreview(all.api, 'selection-atlas-allmatching-120')
    expect(allResult.data?.preview_id).toBe('preview-atlas-allmatching-120')
  })
})

describe('mock preview: hetero — все Prediction/CollisionDetails kinds, nullable', () => {
  it('hetero literal: predictions, collision kinds, nullable target/metadata', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    controller.setPreviewScenario('hetero')

    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)
    expectSchema('Preview', result.data)

    const canned = getExample<Preview>('preview-atlas-hetero')
    expect(result.data?.preview_id).toBe('preview-atlas-hetero')
    expect(result.data?.selection_id).toBe('selection-atlas-explicit-one')
    expect(result.data?.company_id).toBe(canned.company_id)
    expect(result.data?.rule_set).toEqual(canned.rule_set)
    expect(result.data?.total).toBe(canned.total)
    expect(result.data?.counts).toEqual(canned.counts)
    expect(result.data?.rows).toEqual(canned.rows)

    const rows = result.data?.rows ?? []
    const predictions = new Set(rows.map((row) => row.predicted_state))
    expect(predictions).toEqual(
      new Set([
        'WILL_MOVE',
        'WILL_MANUAL_REVIEW',
        'REQUIRES_DECISION',
        'NOT_READY',
      ]),
    )

    const collisions = rows
      .map((row) => row.collision)
      .filter((collision) => collision !== null)
    const kinds = new Set(collisions.map((collision) => collision?.kind))
    expect(kinds).toEqual(
      new Set(['EXISTING_TARGET', 'DUPLICATE_PLAN_TARGET', 'MANUAL_REVIEW_NAME']),
    )

    const existing = collisions.find(
      (collision) => collision?.kind === 'EXISTING_TARGET',
    )
    expect(existing?.existing_target_metadata).not.toBeNull()

    const duplicate = collisions.find(
      (collision) => collision?.kind === 'DUPLICATE_PLAN_TARGET',
    )
    expect(duplicate?.existing_target_metadata).toBeNull()
    expect(duplicate?.conflicting_item_ids).toHaveLength(2)

    const manual = collisions.find(
      (collision) => collision?.kind === 'MANUAL_REVIEW_NAME',
    )
    expect(manual?.existing_target_metadata).not.toBeNull()

    // Nullable target присутствует буквально: часть строк без цели.
    expect(rows.some((row) => row.target === null)).toBe(true)
    expect(rows.some((row) => row.target !== null)).toBe(true)
  })
})

describe('mock preview: conflict — RULE_CONFLICT', () => {
  it('conflict literal: counts.rule_conflicts, matched_rules, selected_rule=null', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    controller.setPreviewScenario('conflict')

    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)
    expectSchema('Preview', result.data)

    const canned = getExample<Preview>('preview-atlas-conflict')
    expect(result.data?.preview_id).toBe('preview-atlas-conflict')
    expect(result.data?.counts).toEqual(canned.counts)
    expect(result.data?.counts.rule_conflicts).toBe(1)
    expect(result.data?.rows).toEqual(canned.rows)
    expect(result.data?.rows[0].reason_code).toBe('RULE_CONFLICT')
    expect(result.data?.rows[0].selected_rule).toBeNull()
    expect(result.data?.rows[0].matched_rules).toHaveLength(2)
  })

  it('все объявленные preview-сценарии разрешаются в schema-valid ответ', () => {
    expect(PREVIEW_SCENARIOS).toHaveLength(5)
    for (const scenario of PREVIEW_SCENARIOS) {
      const sample = scenarioExampleId(scenario)
      const preview = getExample<Preview>(sample)
      expectSchema('Preview', preview)
    }
  })
})

function scenarioExampleId(scenario: PreviewScenario): string {
  switch (scenario) {
    case 'explicit-one':
      return 'preview-atlas-explicit-one'
    case 'explicit-multiple':
      return 'preview-atlas-explicit-multiple'
    case 'allmatching-120':
      return 'preview-atlas-allmatching-120-page1'
    case 'hetero':
      return 'preview-atlas-hetero'
    case 'conflict':
      return 'preview-atlas-conflict'
  }
}

describe('mock preview: movement не выполняется', () => {
  it('create не создаёт batch и не меняет снимок выбора', async () => {
    const { api, controller, calls } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    const before = controller
      .getSelectionStore()
      .get('selection-atlas-explicit-one')
    expect(before?.snapshot.selected_count).toBe(1)

    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)

    // Никакого POST /sorting/batches (movement/executor не запускается).
    expect(calls.some((call) => call.includes('/sorting/batches'))).toBe(false)
    expect(
      calls.filter((call) => call === 'POST /api/v1/sorting/previews'),
    ).toHaveLength(1)

    const after = controller
      .getSelectionStore()
      .get('selection-atlas-explicit-one')
    expect(after).toEqual(before)
  })
})

describe('mock preview: owner/expiry/unknown снимка через SelectionStore', () => {
  it('владелец — 201; другой пользователь — 403 FORBIDDEN', async () => {
    const { api } = setup()
    await loginWithCsrf(api, 'auth-login-request-worker-one')
    await postSelection(api, EXPLICIT_ONE)

    const own = await postPreview(api, 'selection-atlas-explicit-one')
    expect(own.response.status).toBe(201)

    await loginWithCsrf(api, 'auth-login-request-worker-two')
    const foreign = await postPreview(api, 'selection-atlas-explicit-one')
    expect(foreign.response.status).toBe(403)
    expect(foreign.error?.error.code).toBe('FORBIDDEN')
    expectSchema('ErrorResponse', foreign.error)
  })

  it('неизвестный снимок — 404 NOT_FOUND', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await postPreview(api, 'selection-unknown')
    expect(result.response.status).toBe(404)
    expect(result.error?.error.code).toBe('NOT_FOUND')
    expectSchema('ErrorResponse', result.error)
  })

  it('истёкший снимок — 409 SELECTION_EXPIRED (до создания preview)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)

    controller.setSelectionNow('2031-05-10T09:36:00Z')
    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(409)
    expect(result.error?.error.code).toBe('SELECTION_EXPIRED')
    expectSchema('ErrorResponse', result.error)
    expect(controller.getPreviewStore().list()).toHaveLength(0)
  })
})

describe('mock preview: get paging/limit/cursor и TTL', () => {
  it('page1 без курсора → 200 literal; declared cursor → 422', async () => {
    const { api } = setup()
    await loginWithCsrf(api)
    await postSelection(api, allMatching(120))
    const created = await postPreview(api, 'selection-atlas-allmatching-120')
    expect(created.response.status).toBe(201)

    const first = await getPreview(api, 'preview-atlas-allmatching-120')
    expect(first.response.status).toBe(200)
    expect(first.data).toEqual(
      getExample<Preview>('preview-atlas-allmatching-120-page1'),
    )
    expectSchema('Preview', first.data)

    const second = await getPreview(api, 'preview-atlas-allmatching-120', {
      cursor: 'cursor-preview-atlas-allmatching-0101',
    })
    expect(second.response.status).toBe(422)
    expect(second.error?.error.code).toBe('VALIDATION_ERROR')
  })

  it('limit 1..100 валидируется; вне диапазона → 422', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    await postPreview(api, 'selection-atlas-explicit-one')

    const valid = await getPreview(api, 'preview-atlas-explicit-one', {
      limit: 100,
    })
    expect(valid.response.status).toBe(200)

    const zero = await getPreview(api, 'preview-atlas-explicit-one', {
      limit: 0,
    })
    expect(zero.response.status).toBe(422)
    expect(zero.error?.error.code).toBe('VALIDATION_ERROR')

    const tooBig = await getPreview(api, 'preview-atlas-explicit-one', {
      limit: 101,
    })
    expect(tooBig.response.status).toBe(422)

    const notNumber = await mockFetch(
      request('/sorting/previews/preview-atlas-explicit-one?limit=abc'),
    )
    expect(notNumber.status).toBe(422)
    expect((await readError(notNumber)).error.code).toBe('VALIDATION_ERROR')
  })

  it('неизвестный preview_id → 404 NOT_FOUND', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await getPreview(api, 'preview-unknown')
    expect(result.response.status).toBe(404)
    expect(result.error?.error.code).toBe('NOT_FOUND')
  })

  it('чтение не продлевает expires_at и не меняет сохранённый preview', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    const created = await postPreview(api, 'selection-atlas-explicit-one')
    const expiresAt = created.data?.expires_at
    expect(expiresAt).toBe('2031-05-10T09:36:00Z')

    controller.setPreviewNow('2031-05-10T10:00:00Z')
    const read = await getPreview(api, 'preview-atlas-explicit-one')
    expect(read.response.status).toBe(200)
    expect(read.data?.expires_at).toBe(expiresAt)
    expect(
      controller.getPreviewStore().get('preview-atlas-explicit-one')?.preview
        .expires_at,
    ).toBe(expiresAt)
    expect(
      controller
        .getPreviewStore()
        .isExpired('preview-atlas-explicit-one', '2031-05-10T10:00:00Z'),
    ).toBe(true)
  })
})

describe('mock preview: 401/403/422', () => {
  it('без сессии → 401 (create и get)', async () => {
    const { api } = setup()

    const create = await postPreview(api, 'selection-atlas-explicit-one')
    expect(create.response.status).toBe(401)
    expect(create.error?.error.code).toBe('UNAUTHENTICATED')

    const get = await getPreview(api, 'preview-atlas-explicit-one')
    expect(get.response.status).toBe(401)
    expect(get.error?.error.code).toBe('UNAUTHENTICATED')
  })

  it('create без/с неверным CSRF → 403, preview не создаётся', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)
    await postSelection(api, EXPLICIT_ONE)

    const noToken = await postPreview(api, 'selection-atlas-explicit-one')
    expect(noToken.response.status).toBe(403)
    expect(noToken.error?.error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrong = await postPreview(api, 'selection-atlas-explicit-one')
    expect(wrong.response.status).toBe(403)
    expect(controller.getPreviewStore().list()).toHaveLength(0)
  })

  it('невалидное тело create → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const missing = await mockFetch(
      request('/sorting/previews', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({}),
      }),
    )
    expect(missing.status).toBe(422)
    expect((await readError(missing)).error.code).toBe('VALIDATION_ERROR')

    const extra = await mockFetch(
      request('/sorting/previews', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: JSON.stringify({
          selection_id: 'selection-atlas-explicit-one',
          preview_id: 'preview-atlas-explicit-one',
        }),
      }),
    )
    expect(extra.status).toBe(422)
    expect((await readError(extra)).error.code).toBe('VALIDATION_ERROR')

    const broken = await mockFetch(
      request('/sorting/previews', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
        },
        body: '{',
      }),
    )
    expect(broken.status).toBe(422)
  })
})

describe('mock preview: управляемые ошибки и per-operation ограничение', () => {
  it('setError createSortingPreview использует объявленные коды', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)

    controller.setError('createSortingPreview', 'INVALID_STATE')
    const conflict = await postPreview(api, 'selection-atlas-explicit-one')
    expect(conflict.response.status).toBe(409)
    expect(conflict.error?.error.code).toBe('INVALID_STATE')
    expectSchema('ErrorResponse', conflict.error)

    controller.clearError('createSortingPreview')
    controller.setError('createSortingPreview', 'SELECTION_EXPIRED')
    const expired = await postPreview(api, 'selection-unknown')
    expect(expired.response.status).toBe(409)
    expect(expired.error?.error.code).toBe('SELECTION_EXPIRED')
  })

  it('failNext getSortingPreview расходуется один раз (SERVICE_UNAVAILABLE)', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    await postPreview(api, 'selection-atlas-explicit-one')
    controller.failNext('getSortingPreview', 'SERVICE_UNAVAILABLE')

    const first = await getPreview(api, 'preview-atlas-explicit-one')
    expect(first.response.status).toBe(503)
    expect(first.error?.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(first.error?.error.retryable).toBe(true)
    expect(first.error?.error.operation_id).toBeNull()
    expect(first.error?.error.field_errors).toEqual([])
    expectSchema('ErrorResponse', first.error)

    const second = await getPreview(api, 'preview-atlas-explicit-one')
    expect(second.response.status).toBe(200)
  })

  it('per-operation: 409-коды getSortingPreview и STALE_PREVIEW не объявлены', () => {
    expect(
      isSortingErrorDeclaredForOperation(
        'getSortingPreview',
        'SELECTION_EXPIRED',
      ),
    ).toBe(false)
    expect(
      isSortingErrorDeclaredForOperation('getSortingPreview', 'NOT_FOUND'),
    ).toBe(true)
    expect(
      isSortingErrorDeclaredForOperation(
        'createSortingPreview',
        'STALE_PREVIEW' as MockSortingErrorCode,
      ),
    ).toBe(false)
    expect(sortingErrorCodesByOperation.getSortingPreview).not.toContain(
      'SELECTION_EXPIRED',
    )
    expect(sortingErrorCodesByOperation.createSortingPreview).not.toContain(
      'STALE_PREVIEW',
    )
    // STALE_PREVIEW доступен инфраструктуре LT-07.2c, но не preview-операциям.
    expect(declaredSelectionUseErrors).toHaveProperty('STALE_PREVIEW')
  })

  it('STALE_PREVIEW доступен управляемо, но runtime-guard не отдаёт его preview', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)

    const stale = selectionUseErrorResponse('request-mock-x', 'STALE_PREVIEW')
    expect(stale.status).toBe(409)
    expect((await readError(stale)).error.code).toBe('STALE_PREVIEW')

    const rawSetError = controller.setError as unknown as (
      operation: MockSortingOperation,
      code: MockSortingErrorCode,
    ) => void
    rawSetError(
      'createSortingPreview',
      'STALE_PREVIEW' as MockSortingErrorCode,
    )

    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)
  })

  it('preview-коды распознаются, queue/selection-коды не подменяются', () => {
    expect(isPreviewErrorCode('INVALID_STATE')).toBe(true)
    expect(isPreviewErrorCode('SELECTION_EXPIRED')).toBe(true)
    expect(isPreviewErrorCode('EMPTY_SELECTION')).toBe(false)
    expect(isPreviewErrorCode('STALE_PREVIEW')).toBe(false)
  })
})

describe('mock preview: reset', () => {
  it('reset очищает сценарий/now/store/errors и восстанавливает вывод из снимка', async () => {
    const { api, controller } = setup()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    controller.setPreviewScenario('hetero')
    controller.setPreviewNow('2031-05-10T10:00:00Z')
    await postPreview(api, 'selection-atlas-explicit-one')
    expect(controller.getPreviewStore().list()).toHaveLength(1)
    controller.failNext('createSortingPreview', 'INTERNAL_ERROR')

    controller.reset()

    expect(controller.getPreviewScenario()).toBeNull()
    expect(controller.getPreviewNow()).toBeNull()
    expect(controller.getPreviewStore().list()).toHaveLength(0)
    expect(controller.getSelectionStore().list()).toHaveLength(0)

    resetSessionContext()
    await loginWithCsrf(api)
    await postSelection(api, EXPLICIT_ONE)
    const result = await postPreview(api, 'selection-atlas-explicit-one')
    expect(result.response.status).toBe(201)
    expect(result.data).toEqual(
      getExample<Preview>('preview-atlas-explicit-one'),
    )
  })
})
