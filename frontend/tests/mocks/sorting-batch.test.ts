// LT-07.2c: контрактные mocks партий
// (`createSortingBatch`/`getSortingBatch`/`listSortingBatches`) без claim,
// executor, matcher и файловых действий.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/идемпотентность/error-модель, что и real) и через mock-fetch
// напрямую для явного `Idempotency-Key` и невалидных запросов. Все успешные
// ответы дополнительно валидируются по схемам OAS.
//
// Партии отдают literal canned-сценарии из
// `contracts/examples/sorting/batch-*.json`: submit DIRECT/PREVIEWED,
// идемпотентный replay/lost response, gates до принятия, прогресс по фазам,
// все BatchState/OutcomeState/reason_code, paging и recovery. Movement не
// выполняется.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  BATCH_PHASES,
  BATCH_SCENARIOS,
  batchErrorCodesByOperation,
  declaredBatchErrors,
  getCannedBatchPage1,
  getCannedBatchPages,
  isBatchErrorDeclaredForOperation,
  RETRY_AFTER_HEADER,
} from '@/mocks'
import {
  createMockFetch,
  MockController,
  type BatchPhase,
  type MockBatchErrorCode,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type {
  Batch,
  BatchCreateRequest,
  BatchPage,
  ErrorResponse,
  LoginRequest,
  SelectionRequest,
  Session,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
  /** Метод и путь каждого реально ушедшего запроса. */
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

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
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
const NOVA = 'company-demo-nova'

const KEY_DIRECT = '11111111-1111-4111-8111-111111111111'
const KEY_PREVIEWED = '22222222-2222-4222-8222-222222222222'
const KEY_REUSE = '33333333-3333-4333-8333-333333333333'
const KEY_NEW = '44444444-4444-4444-8444-444444444444'

const EXPLICIT_ONE: SelectionRequest = {
  company_id: ATLAS,
  mode: 'EXPLICIT',
  items: [{ item_id: 'queue-atlas-ready-0001', item_revision: 1 }],
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

interface RawBatchOptions {
  csrfToken?: string | null
  idempotencyKey?: string
}

/** Сырой POST /sorting/batches с явным Idempotency-Key (для replay/reuse). */
function batchRequest(
  body: unknown,
  options: RawBatchOptions = {},
): Request {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.csrfToken !== null) {
    headers['X-CSRF-Token'] = options.csrfToken ?? 'caller-placeholder'
  }
  if (options.idempotencyKey !== undefined) {
    headers['Idempotency-Key'] = options.idempotencyKey
  }
  return request('/sorting/batches', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
}

function getBatchRequest(
  batchId: string,
  query?: { cursor?: string; limit?: number },
): Request {
  const params = new URLSearchParams()
  if (query?.cursor !== undefined) {
    params.set('cursor', query.cursor)
  }
  if (query?.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : ''
  return request(`/sorting/batches/${batchId}${suffix}`)
}

function listRequest(
  companyId: string | null,
  query?: { cursor?: string; limit?: number },
): Request {
  const params = new URLSearchParams()
  if (companyId !== null) {
    params.set('company_id', companyId)
  }
  if (query?.cursor !== undefined) {
    params.set('cursor', query.cursor)
  }
  if (query?.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : ''
  return request(`/sorting/batches${suffix}`)
}

/**
 * Создаёт снимок ALL_MATCHING 120 и возвращает его id
 * (`selection-atlas-allmatching-120`).
 */
async function createAllMatching120(api: WiseWayApiClient): Promise<string> {
  const created = await postSelection(api, allMatching(120))
  expect(created.response.status).toBe(201)
  return 'selection-atlas-allmatching-120'
}

/** Проверяет согласованность counts/completed_count/статуса партии. */
function assertCountsConsistent(batch: Batch): void {
  const counts = batch.counts
  const established =
    counts.sorted +
    counts.manual_review +
    counts.requires_decision +
    counts.quarantined +
    counts.skipped
  expect(established).toBe(batch.completed_count)
  if (batch.status === 'COMPLETED' || batch.status === 'COMPLETED_WITH_ISSUES') {
    expect(batch.finished_at).not.toBeNull()
    expect(counts.recovery_required).toBe(0)
    expect(batch.completed_count).toBe(batch.selected_count)
  }
  if (
    batch.status === 'ACCEPTED' ||
    batch.status === 'RUNNING' ||
    batch.status === 'RECOVERY_REQUIRED'
  ) {
    expect(batch.finished_at).toBeNull()
  }
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация партий', () => {
  it('регистрирует create/get/list и извлекает batch_id', () => {
    const create = matchMockRoute('POST', '/sorting/batches')
    expect(create).toBeDefined()
    expect(create?.params).toEqual({})

    const list = matchMockRoute('GET', '/sorting/batches')
    expect(list).toBeDefined()
    expect(list?.params).toEqual({})

    const get = matchMockRoute('GET', '/sorting/batches/batch-atlas-sorted')
    expect(get).toBeDefined()
    expect(get?.params).toEqual({ batch_id: 'batch-atlas-sorted' })
  })

  it('успешные ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const created = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(created.status).toBe(202)
    expect(created.headers.get('Cache-Control')).toBe('no-store')
    expect(created.headers.get('X-Request-ID')).toMatch(/^request-mock-\d+$/)
    expect(created.headers.get('X-WiseWay-Mock')).toBe('mock')

    const read = await mockFetch(
      getBatchRequest('batch-atlas-direct-fresh'),
    )
    expect(read.status).toBe(200)
    expect(read.headers.get('X-WiseWay-Mock')).toBe('mock')
  })
})

describe('mock batch: submit DIRECT/PREVIEWED → 202 literal', () => {
  it('DIRECT → 202 literal batch-atlas-direct-fresh-page1 (ACCEPTED, 202 ≠ завершение)', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(202)
    const batch = await readJson<Batch>(response)
    expect(batch).toEqual(
      getExample<Batch>('batch-atlas-direct-fresh-page1'),
    )
    expectSchema('Batch', batch)
    expect(batch.status).toBe('ACCEPTED')
    expect(batch.finished_at).toBeNull()
    expect(batch.preview_id).toBeNull()
    expect(batch.outcomes).toHaveLength(100)
    expect(batch.outcomes.every((outcome) => outcome.state === 'PENDING')).toBe(
      true,
    )
    assertCountsConsistent(batch)
    expect(controller.getBatchStore().get('batch-atlas-direct-fresh')).toBeDefined()
  })

  it('PREVIEWED → 202 literal batch-atlas-previewed-fresh-page1 (RUNNING)', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const preview = await postPreview(api, 'selection-atlas-allmatching-120')
    expect(preview.response.status).toBe(201)

    const response = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-atlas-allmatching-120',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(response.status).toBe(202)
    const batch = await readJson<Batch>(response)
    expect(batch).toEqual(
      getExample<Batch>('batch-atlas-previewed-fresh-page1'),
    )
    expectSchema('Batch', batch)
    expect(batch.status).toBe('RUNNING')
    expect(batch.finished_at).toBeNull()
    expect(batch.preview_id).toBe('preview-atlas-allmatching-120')
    expect(batch.completed_count).toBe(118)
    assertCountsConsistent(batch)
  })

  it('создание партии не выполняет movement и не меняет снимок выбора', async () => {
    const { api, controller, calls, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const before = controller
      .getSelectionStore()
      .get('selection-atlas-allmatching-120')
    expect(before?.snapshot.selected_count).toBe(120)

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(202)

    expect(
      calls.filter((call) => call === 'POST /api/v1/sorting/batches'),
    ).toHaveLength(1)
    expect(
      controller.getSelectionStore().get('selection-atlas-allmatching-120'),
    ).toEqual(before)
  })
})

describe('mock batch: идемпотентность (lost response/retry/reuse/new key)', () => {
  it('same key+body → тот же batch (replay)', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const body: BatchCreateRequest = {
      selection_id: 'selection-atlas-allmatching-120',
      execution_mode: 'DIRECT',
    }

    const first = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_DIRECT,
      }),
    )
    expect(first.status).toBe(202)
    const firstBatch = await readJson<Batch>(first)

    const replay = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_DIRECT,
      }),
    )
    expect(replay.status).toBe(202)
    expect(await readJson<Batch>(replay)).toEqual(firstBatch)
  })

  it('replay принятой партии работает при устаревшем selection (до staleness)', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const body: BatchCreateRequest = {
      selection_id: 'selection-atlas-allmatching-120',
      execution_mode: 'DIRECT',
    }

    const first = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_DIRECT,
      }),
    )
    const firstBatch = await readJson<Batch>(first)

    // Снимок истёк, но ключ принятой партии проверяется раньше TTL.
    controller.setSelectionNow('2031-05-10T09:36:00Z')
    const replay = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_DIRECT,
      }),
    )
    expect(replay.status).toBe(202)
    expect(await readJson<Batch>(replay)).toEqual(firstBatch)
  })

  it('same key + другое тело → 409 IDEMPOTENCY_KEY_REUSED, партия не создаётся', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const preview = await postPreview(api, 'selection-atlas-allmatching-120')
    expect(preview.response.status).toBe(201)

    await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_REUSE },
      ),
    )
    const stored = controller.getBatchStore().list().length

    const reused = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-atlas-allmatching-120',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_REUSE },
      ),
    )
    expect(reused.status).toBe(409)
    const error = await readError(reused)
    expect(error.error.code).toBe('IDEMPOTENCY_KEY_REUSED')
    expectSchema('ErrorResponse', error)
    expect(controller.getBatchStore().list()).toHaveLength(stored)
  })

  it('новый key → новая партия с уникальным batch_id', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    const body: BatchCreateRequest = {
      selection_id: 'selection-atlas-allmatching-120',
      execution_mode: 'DIRECT',
    }

    const first = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_DIRECT,
      }),
    )
    const firstBatch = await readJson<Batch>(first)
    expect(firstBatch.batch_id).toBe('batch-atlas-direct-fresh')

    const second = await mockFetch(
      batchRequest(body, {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_NEW,
      }),
    )
    expect(second.status).toBe(202)
    const secondBatch = await readJson<Batch>(second)
    expect(secondBatch.batch_id).not.toBe(firstBatch.batch_id)
    expectSchema('Batch', secondBatch)
    expect(controller.getBatchStore().list()).toHaveLength(2)
    // Обе партии доступны по своим id.
    expect(
      (await mockFetch(getBatchRequest(firstBatch.batch_id))).status,
    ).toBe(200)
    expect(
      (await mockFetch(getBatchRequest(secondBatch.batch_id))).status,
    ).toBe(200)
  })

  it('user-scoped: тот же ключ у другого пользователя — своя партия', async () => {
    const { api, mockFetch } = setup()
    const workerOne = await loginWithCsrf(api, 'auth-login-request-worker-one')
    await createAllMatching120(api)

    const first = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: workerOne.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(first.status).toBe(202)

    const workerTwo = await loginWithCsrf(api, 'auth-login-request-worker-two')
    // Другой пользователь создаёт свой снимок и партию с тем же ключом.
    const created = await postSelection(api, EXPLICIT_ONE)
    expect(created.response.status).toBe(201)
    const scoped = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-explicit-one', execution_mode: 'DIRECT' },
        { csrfToken: workerTwo.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(scoped.status).toBe(202)
    const scopedBatch = await readJson<Batch>(scoped)
    expect(scopedBatch.selection_id).toBe('selection-atlas-explicit-one')
    expect(scopedBatch.actor.user_id).toBe('user-demo-worker-2')
  })
})

describe('mock batch: gates до принятия партии', () => {
  it('неизвестный selection → 404 NOT_FOUND', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-unknown', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(404)
    const error = await readError(response)
    expect(error.error.code).toBe('NOT_FOUND')
    expectSchema('ErrorResponse', error)
  })

  it('неизвестный preview → 404 NOT_FOUND', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const response = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-unknown',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(response.status).toBe(404)
    expect((await readError(response)).error.code).toBe('NOT_FOUND')
  })

  it('чужой selection → 403 FORBIDDEN', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-worker-one')
    await createAllMatching120(api)

    const workerTwo = await loginWithCsrf(api, 'auth-login-request-worker-two')
    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: workerTwo.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(403)
    expect((await readError(response)).error.code).toBe('FORBIDDEN')
  })

  it('истёкший selection → 409 SELECTION_EXPIRED', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    controller.setSelectionNow('2031-05-10T09:36:00Z')

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(409)
    expect((await readError(response)).error.code).toBe('SELECTION_EXPIRED')
  })

  it('preview другой пары → 409 INVALID_STATE', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    // Снимок/preview одной пары…
    const one = await postSelection(api, EXPLICIT_ONE)
    expect(one.response.status).toBe(201)
    const preview = await postPreview(api, 'selection-atlas-explicit-one')
    expect(preview.response.status).toBe(201)

    // …используется с другим selection.
    const response = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-atlas-explicit-one',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(response.status).toBe(409)
    expect((await readError(response)).error.code).toBe('INVALID_STATE')
  })

  it('DIRECT с изменённым источником → 409 SELECTION_CHANGED', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    controller.setBatchGate('SELECTION_CHANGED')

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(409)
    expect((await readError(response)).error.code).toBe('SELECTION_CHANGED')
    expect(controller.getBatchStore().list()).toHaveLength(0)
  })

  it('PREVIEWED с устаревшим preview → 409 STALE_PREVIEW (gate и TTL)', async () => {
    const gateSetup = setup()
    const gateSession = await loginWithCsrf(gateSetup.api)
    await createAllMatching120(gateSetup.api)
    await postPreview(gateSetup.api, 'selection-atlas-allmatching-120')
    gateSetup.controller.setBatchGate('STALE_PREVIEW')

    const gated = await gateSetup.mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-atlas-allmatching-120',
        },
        { csrfToken: gateSession.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(gated.status).toBe(409)
    expect((await readError(gated)).error.code).toBe('STALE_PREVIEW')

    const ttlSetup = setup()
    const ttlSession = await loginWithCsrf(ttlSetup.api)
    await createAllMatching120(ttlSetup.api)
    await postPreview(ttlSetup.api, 'selection-atlas-allmatching-120')
    ttlSetup.controller.setPreviewNow('2031-05-10T09:36:00Z')

    const expired = await ttlSetup.mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
          preview_id: 'preview-atlas-allmatching-120',
        },
        { csrfToken: ttlSession.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(expired.status).toBe(409)
    expect((await readError(expired)).error.code).toBe('STALE_PREVIEW')
  })

  it('превышен предел партии → 422 VALIDATION_ERROR', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    controller.setBatchGate('BATCH_LIMIT_EXCEEDED')

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.some((f) => f.code === 'BATCH_LIMIT_EXCEEDED')).toBe(
      true,
    )
  })

  it('отсутствует Idempotency-Key → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token },
      ),
    )
    expect(response.status).toBe(422)
    const error = await readError(response)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expect(error.error.field_errors.some((f) => f.field === 'Idempotency-Key')).toBe(
      true,
    )
  })

  it('невалидное тело oneOf DIRECT/PREVIEWED → 422', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const directWithPreview = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'DIRECT',
          preview_id: 'preview-atlas-allmatching-120',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(directWithPreview.status).toBe(422)

    const previewedWithoutPreview = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'PREVIEWED',
        },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_PREVIEWED },
      ),
    )
    expect(previewedWithoutPreview.status).toBe(422)

    const extraField = await mockFetch(
      batchRequest(
        {
          selection_id: 'selection-atlas-allmatching-120',
          execution_mode: 'DIRECT',
          comment: 'лишнее',
        } as unknown as BatchCreateRequest,
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(extraField.status).toBe(422)
  })
})

describe('mock batch: get — paging, прогресс, все состояния/исходы/recovery', () => {
  it('page1/page2 по непрозрачному cursor; неизвестный cursor → 422', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )

    const page1 = await mockFetch(getBatchRequest('batch-atlas-direct-fresh'))
    expect(page1.status).toBe(200)
    const first = await readJson<Batch>(page1)
    expect(first).toEqual(getExample<Batch>('batch-atlas-direct-fresh-page1'))
    expect(first.outcomes).toHaveLength(100)
    expect(first.next_cursor).toBe('cursor-batch-atlas-direct-fresh-page2')

    const page2 = await mockFetch(
      getBatchRequest('batch-atlas-direct-fresh', {
        cursor: 'cursor-batch-atlas-direct-fresh-page2',
      }),
    )
    expect(page2.status).toBe(200)
    const second = await readJson<Batch>(page2)
    expect(second).toEqual(getExample<Batch>('batch-atlas-direct-fresh-page2'))
    expect(second.outcomes).toHaveLength(20)
    expect(second.next_cursor).toBeNull()

    const bad = await mockFetch(
      getBatchRequest('batch-atlas-direct-fresh', { cursor: 'unknown-cursor' }),
    )
    expect(bad.status).toBe(422)
    expect((await readError(bad)).error.code).toBe('VALIDATION_ERROR')
  })

  it('прогресс по фазам ACCEPTED→RUNNING→COMPLETED→COMPLETED_WITH_ISSUES→RECOVERY_REQUIRED', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )

    const expectedStatus: Record<BatchPhase, Batch['status']> = {
      ACCEPTED: 'ACCEPTED',
      RUNNING: 'RUNNING',
      COMPLETED: 'COMPLETED',
      COMPLETED_WITH_ISSUES: 'COMPLETED_WITH_ISSUES',
      RECOVERY_REQUIRED: 'RECOVERY_REQUIRED',
    }
    for (const phase of BATCH_PHASES) {
      controller.setBatchPhase(phase)
      const response = await mockFetch(
        getBatchRequest('batch-atlas-direct-fresh'),
      )
      expect(response.status).toBe(200)
      const batch = await readJson<Batch>(response)
      expectSchema('Batch', batch)
      expect(batch.batch_id).toBe('batch-atlas-direct-fresh')
      expect(batch.status).toBe(expectedStatus[phase])
      assertCountsConsistent(batch)
    }
  })

  it('все BatchState/OutcomeState/reason_code достижимы canned-сценариями', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()

    const states = new Set<string>()
    const reasons = new Set<string | null>()
    const statuses = new Set<string>()

    const readPage = async (batchId: string, cursor?: string) => {
      const response = await mockFetch(getBatchRequest(batchId, { cursor }))
      expect(response.status).toBe(200)
      const batch = await readJson<Batch>(response)
      expectSchema('Batch', batch)
      statuses.add(batch.status)
      for (const outcome of batch.outcomes) {
        states.add(outcome.state)
        reasons.add(outcome.reason_code)
      }
      assertCountsConsistent(batch)
      return batch
    }

    await readPage('batch-atlas-direct-fresh')
    await readPage(
      'batch-atlas-previewed-fresh',
      'cursor-batch-atlas-previewed-fresh-page2',
    )
    await readPage('batch-atlas-sorted')
    await readPage('batch-atlas-conflict')
    await readPage('batch-atlas-hetero')
    await readPage('batch-atlas-technical')

    expect(statuses).toEqual(
      new Set([
        'ACCEPTED',
        'RUNNING',
        'COMPLETED',
        'COMPLETED_WITH_ISSUES',
        'RECOVERY_REQUIRED',
      ]),
    )
    expect(states).toEqual(
      new Set([
        'PENDING',
        'PROCESSING',
        'SORTED',
        'MANUAL_REVIEW',
        'REQUIRES_DECISION',
        'QUARANTINED',
        'SKIPPED',
        'RECOVERY_REQUIRED',
      ]),
    )
    expect(reasons).toEqual(
      new Set([
        null,
        'NO_SCENARIO',
        'RULE_CONFLICT',
        'TARGET_OCCUPIED',
        'MANUAL_REVIEW_NAME_OCCUPIED',
        'TECHNICAL_ERROR',
        'ALREADY_PROCESSING',
        'SOURCE_CHANGED',
        'SOURCE_MISSING',
        'RECOVERY_REQUIRED',
      ]),
    )
  })

  it('RECOVERY_REQUIRED не завершена: finished_at=null, recovery_required>0', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()

    const response = await mockFetch(getBatchRequest('batch-atlas-technical'))
    expect(response.status).toBe(200)
    const batch = await readJson<Batch>(response)
    expect(batch.status).toBe('RECOVERY_REQUIRED')
    expect(batch.finished_at).toBeNull()
    expect(batch.counts.recovery_required).toBeGreaterThan(0)
    expect(batch.completed_count).toBeLessThan(batch.selected_count)
    assertCountsConsistent(batch)
  })

  it('override сценария и фазы привязывают identity к созданной партии', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()
    controller.setBatchScenario('hetero')

    const response = await mockFetch(getBatchRequest('batch-atlas-direct-fresh'))
    expect(response.status).toBe(200)
    const batch = await readJson<Batch>(response)
    expect(batch.batch_id).toBe('batch-atlas-direct-fresh')
    expect(batch.selection_id).toBe('selection-atlas-allmatching-120')
    expect(batch.status).toBe('COMPLETED_WITH_ISSUES')
    expectSchema('Batch', batch)
  })

  it('неизвестный batch_id → 404; невалидный limit → 422', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const unknown = await mockFetch(getBatchRequest('batch-unknown'))
    expect(unknown.status).toBe(404)
    expect((await readError(unknown)).error.code).toBe('NOT_FOUND')

    const badLimit = await mockFetch(
      getBatchRequest('batch-atlas-direct-fresh', { limit: 0 }),
    )
    expect(badLimit.status).toBe(422)
    expect((await readError(badLimit)).error.code).toBe('VALIDATION_ERROR')
  })
})

describe('mock batch: list — company-scoped, порядок, cursor', () => {
  it('company-scoped: Atlas = literal история, другая компания пуста', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()

    const atlas = await mockFetch(listRequest(ATLAS))
    expect(atlas.status).toBe(200)
    const page = await readJson<BatchPage>(atlas)
    expectSchema('BatchPage', page)
    expect(page).toEqual(getExample<BatchPage>('batch-history-atlas-page1'))
    expect(page.items).toHaveLength(7)
    expect(page.next_cursor).toBeNull()

    const nova = await mockFetch(listRequest(NOVA))
    expect(nova.status).toBe(200)
    const empty = await readJson<BatchPage>(nova)
    expect(empty.items).toHaveLength(0)
    expect(empty.next_cursor).toBeNull()
  })

  it('порядок created_at DESC, batch_id DESC', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()

    const response = await mockFetch(listRequest(ATLAS))
    const page = await readJson<BatchPage>(response)
    const ids = page.items.map((item) => item.batch_id)
    expect(ids).toEqual([
      'batch-atlas-technical',
      'batch-atlas-sorted',
      'batch-atlas-conflict',
      'batch-atlas-hetero',
      'batch-atlas-same-user-session',
      'batch-atlas-previewed-fresh',
      'batch-atlas-direct-fresh',
    ])
  })

  it('cursor/limit finite: limit=3 → next page; неизвестный cursor → 422', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.seedBatchHistory()

    const first = await mockFetch(listRequest(ATLAS, { limit: 3 }))
    const firstPage = await readJson<BatchPage>(first)
    expect(firstPage.items).toHaveLength(3)
    expect(firstPage.next_cursor).toBe('batches-offset-3')

    const second = await mockFetch(
      listRequest(ATLAS, { cursor: 'batches-offset-3', limit: 3 }),
    )
    const secondPage = await readJson<BatchPage>(second)
    expect(secondPage.items).toHaveLength(3)
    expect(secondPage.next_cursor).toBe('batches-offset-6')

    const bad = await mockFetch(listRequest(ATLAS, { cursor: 'unknown' }))
    expect(bad.status).toBe(422)
    expect((await readError(bad)).error.code).toBe('VALIDATION_ERROR')
  })

  it('company_id обязателен; созданная партия появляется в списке', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const missing = await mockFetch(listRequest(null))
    expect(missing.status).toBe(422)
    const missingError = await readError(missing)
    expect(missingError.error.code).toBe('VALIDATION_ERROR')
    expect(missingError.error.field_errors.some((f) => f.field === 'company_id')).toBe(
      true,
    )

    await createAllMatching120(api)
    const created = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    const batch = await readJson<Batch>(created)

    const list = await mockFetch(listRequest(ATLAS))
    const page = await readJson<BatchPage>(list)
    expect(page.items).toHaveLength(1)
    expect(page.items[0].batch_id).toBe(batch.batch_id)
    expect(page.items[0].status).toBe('ACCEPTED')
  })
})

describe('mock batch: 401/403/422 и управляемые ошибки', () => {
  it('без сессии → 401 для create/get/list', async () => {
    const { mockFetch } = setup()

    const create = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: 'x', idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(create.status).toBe(401)
    expect((await readError(create)).error.code).toBe('UNAUTHENTICATED')

    const get = await mockFetch(getBatchRequest('batch-atlas-sorted'))
    expect(get.status).toBe(401)

    const list = await mockFetch(listRequest(ATLAS))
    expect(list.status).toBe(401)
  })

  it('create без/с неверным CSRF → 403, партия не создаётся', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const noToken = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: null, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(noToken.status).toBe(403)
    expect((await readError(noToken)).error.code).toBe('CSRF_FAILED')

    setCsrfToken(`${session.csrf_token}-wrong`)
    const wrong = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        {
          csrfToken: `${session.csrf_token}-wrong`,
          idempotencyKey: KEY_DIRECT,
        },
      ),
    )
    expect(wrong.status).toBe(403)
    expect(controller.getBatchStore().list()).toHaveLength(0)
  })

  it('setError/failNext/clearError работают по объявленным кодам', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    controller.setError('createSortingBatch', 'INVALID_STATE')
    const conflict = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(conflict.status).toBe(409)
    expect((await readError(conflict)).error.code).toBe('INVALID_STATE')
    controller.clearError('createSortingBatch')

    controller.seedBatchHistory()
    controller.failNext('getSortingBatch', 'SERVICE_UNAVAILABLE')
    const first = await mockFetch(getBatchRequest('batch-atlas-sorted'))
    expect(first.status).toBe(503)
    expect(first.headers.get(RETRY_AFTER_HEADER)).toBeNull()
    const error = await readError(first)
    expect(error.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(error.error.retryable).toBe(true)
    expect(error.error.operation_id).toBeNull()
    expect(error.error.field_errors).toEqual([])
    expectSchema('ErrorResponse', error)

    const second = await mockFetch(getBatchRequest('batch-atlas-sorted'))
    expect(second.status).toBe(200)

    controller.failNext('listSortingBatches', 'RATE_LIMITED')
    const limited = await mockFetch(listRequest(ATLAS))
    expect(limited.status).toBe(429)
    expect(limited.headers.get(RETRY_AFTER_HEADER)).toMatch(/^[0-9]+$/)
    expect((await readError(limited)).error.code).toBe('RATE_LIMITED')
  })

  it('per-operation ограничение: 409/404 не объявлены для list, 409 — для get', () => {
    expect(
      isBatchErrorDeclaredForOperation('listSortingBatches', 'NOT_FOUND'),
    ).toBe(false)
    expect(
      isBatchErrorDeclaredForOperation('listSortingBatches', 'INVALID_STATE'),
    ).toBe(false)
    expect(
      isBatchErrorDeclaredForOperation('getSortingBatch', 'SELECTION_EXPIRED'),
    ).toBe(false)
    expect(
      isBatchErrorDeclaredForOperation('getSortingBatch', 'NOT_FOUND'),
    ).toBe(true)
    expect(
      isBatchErrorDeclaredForOperation('createSortingBatch', 'STALE_PREVIEW'),
    ).toBe(true)
    expect(
      isBatchErrorDeclaredForOperation(
        'createSortingBatch',
        'BATCH_LIMIT_EXCEEDED' as MockBatchErrorCode,
      ),
    ).toBe(false)
    expect(batchErrorCodesByOperation.listSortingBatches).not.toContain(
      'NOT_FOUND',
    )
    expect(declaredBatchErrors.STALE_PREVIEW.exampleId).toBe(
      'error-batch-stale-preview',
    )
  })

  it('runtime-guard игнорирует undeclared код для операции', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)

    const rawSetError = controller.setError.bind(controller) as unknown as (
      operation: string,
      code: MockBatchErrorCode,
    ) => void
    rawSetError('createSortingBatch', 'SELECTION_EXPIRED')
    // SELECTION_EXPIRED объявлен для create, поэтому ошибка воспроизводится.
    const declared = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(declared.status).toBe(409)
    controller.clearError('createSortingBatch')

    rawSetError('listSortingBatches', 'NOT_FOUND' as MockBatchErrorCode)
    const ignored = await mockFetch(listRequest(ATLAS))
    expect(ignored.status).toBe(200)
  })
})

describe('mock batch: reset', () => {
  it('reset очищает сценарий/фазу/gate/store/errors', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await createAllMatching120(api)
    controller.setBatchScenario('hetero')
    controller.setBatchPhase('RUNNING')
    controller.setBatchGate('STALE_PREVIEW')
    await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(controller.getBatchStore().list()).toHaveLength(1)

    controller.reset()

    expect(controller.getBatchScenario()).toBeNull()
    expect(controller.getBatchPhase()).toBeNull()
    expect(controller.getBatchGate()).toBeNull()
    expect(controller.getBatchStore().list()).toHaveLength(0)
    expect(controller.getSelectionStore().list()).toHaveLength(0)

    resetSessionContext()
    const newSession = await loginWithCsrf(api)
    await createAllMatching120(api)
    const response = await mockFetch(
      batchRequest(
        { selection_id: 'selection-atlas-allmatching-120', execution_mode: 'DIRECT' },
        { csrfToken: newSession.csrf_token, idempotencyKey: KEY_DIRECT },
      ),
    )
    expect(response.status).toBe(202)
    expect(await readJson<Batch>(response)).toEqual(
      getExample<Batch>('batch-atlas-direct-fresh-page1'),
    )
  })

  it('все объявленные batch-сценарии и фазы разрешаются в schema-valid Batch', () => {
    expect(BATCH_SCENARIOS).toHaveLength(7)
    for (const scenario of BATCH_SCENARIOS) {
      for (const page of getCannedBatchPages(scenario)) {
        expectSchema('Batch', page)
      }
    }
    expect(getCannedBatchPage1('technical').status).toBe('RECOVERY_REQUIRED')
    expect(getCannedBatchPage1('sorted').status).toBe('COMPLETED')
  })
})
