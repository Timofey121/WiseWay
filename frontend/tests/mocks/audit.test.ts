// LT-07.3b: контрактные mocks журнала аудита (`queryAuditEvents`,
// `getAuditUpdates`, `listAuditActors`) без записи, immutability, серверного
// фильтр-алгоритма, cursor-store и actor-directory.
//
// Проверки идут через mock-fetch напрямую (операции чтения, CSRF не нужен) и
// через `createApiClient({ mode: 'mock', fetch })` для входа. Все успешные и
// ошибочные ответы дополнительно валидируются по схемам OAS.
//
// Журнал отдаёт literal canned-данные из `contracts/examples/audit/*.json`:
// day/issue/batch-accepted/cursor-page2/empty, роли WORKER (BUSINESS) и ADMIN
// (BUSINESS+SYSTEM с единственным допустимым null-actor у SYSTEM
// LOGIN_FAILED), обновления `{has_new_events}`, авторов с заблокированным
// автором и связи request/operation/source-attempt/batch/version/dictionary.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  AUDIT_ACTORS_PAGE_ID,
  AUDIT_ATLAS_COMPANY_ID,
  AUDIT_NEWEST_EVENT_ID,
  AUDIT_SCENARIOS,
  AUDIT_WORKER_NEWEST_EVENT_ID,
  auditErrorCodesByOperation,
  declaredAuditErrors,
  isAuditErrorDeclaredForOperation,
} from '@/mocks'
import {
  createMockFetch,
  MockController,
  type MockAuditErrorCode,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type {
  ActorPage,
  AuditEvent,
  AuditQueryRequest,
  AuditQueryResponse,
  AuditUpdatesResponse,
  ErrorResponse,
  LoginRequest,
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

const ATLAS = AUDIT_ATLAS_COMPANY_ID
const NOVA = 'company-demo-nova'

const DAY_FROM = '2031-05-09T21:00:00Z'
const DAY_TO = '2031-05-10T21:00:00Z'
const EMPTY_FROM = '2031-05-10T10:00:00Z'
const EMPTY_TO = '2031-05-10T11:00:00Z'

const PAGE2_CURSOR = 'cursor-audit-atlas-page2'

/** Собирает валидное тело `AuditQueryRequest` с переопределениями. */
function auditQuery(
  overrides: Partial<AuditQueryRequest> = {},
): AuditQueryRequest {
  return {
    company_id: null,
    from: DAY_FROM,
    to: DAY_TO,
    actor_id: null,
    action: null,
    result: null,
    query_text: '',
    cursor: null,
    limit: 100,
    ...overrides,
  }
}

function queryRequest(body: unknown): Request {
  return request('/audit/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function updatesRequest(afterEventId: string | null): Request {
  const params = new URLSearchParams()
  if (afterEventId !== null) {
    params.set('after_event_id', afterEventId)
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : ''
  return request(`/audit/updates${suffix}`)
}

function actorsRequest(query?: {
  prefix?: string
  cursor?: string
  limit?: number
}): Request {
  const params = new URLSearchParams()
  if (query?.prefix !== undefined) {
    params.set('prefix', query.prefix)
  }
  if (query?.cursor !== undefined) {
    params.set('cursor', query.cursor)
  }
  if (query?.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : ''
  return request(`/audit/actors${suffix}`)
}

async function queryAs(
  mockFetch: MockFetch,
  body: AuditQueryRequest,
): Promise<AuditQueryResponse> {
  const response = await mockFetch(queryRequest(body))
  expect(response.status).toBe(200)
  return readJson<AuditQueryResponse>(response)
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация журнала', () => {
  it('регистрирует три операции журнала', () => {
    expect(matchMockRoute('POST', '/audit/query')).toBeDefined()
    expect(matchMockRoute('GET', '/audit/updates')).toBeDefined()
    expect(matchMockRoute('GET', '/audit/actors')).toBeDefined()
  })

  it('ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const query = await mockFetch(queryRequest(auditQuery()))
    expect(query.status).toBe(200)
    expect(query.headers.get('Cache-Control')).toBe('no-store')
    expect(query.headers.get('X-Request-ID')).toMatch(/^request-mock-\d+$/)
    expect(query.headers.get('X-WiseWay-Mock')).toBe('mock')

    const updates = await mockFetch(updatesRequest(AUDIT_NEWEST_EVENT_ID))
    expect(updates.status).toBe(200)
    expect(updates.headers.get('X-WiseWay-Mock')).toBe('mock')

    const actors = await mockFetch(actorsRequest())
    expect(actors.status).toBe(200)
    expect(actors.headers.get('X-WiseWay-Mock')).toBe('mock')
  })
})

describe('mock audit query: literal canned-страницы', () => {
  it('day-atlas: literal items/order/next_cursor/newest_event_id', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(mockFetch, auditQuery({ company_id: ATLAS }))
    expect(page).toEqual(
      getExample<AuditQueryResponse>('audit-query-day-atlas'),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.items.length).toBeGreaterThan(0)
    expect(page.next_cursor).toBe(PAGE2_CURSOR)
    expect(page.newest_event_id).toBe(AUDIT_WORKER_NEWEST_EVENT_ID)

    // Порядок occurred_at DESC, затем event_id DESC.
    for (let index = 1; index < page.items.length; index += 1) {
      const previous = page.items[index - 1]
      const current = page.items[index]
      const ordered =
        previous.occurred_at > current.occurred_at ||
        (previous.occurred_at === current.occurred_at &&
          previous.event_id > current.event_id)
      expect(ordered, `${previous.event_id} → ${current.event_id}`).toBe(true)
    }
  })

  it('batch-accepted: action=BATCH_ACCEPTED → literal страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(
      mockFetch,
      auditQuery({ action: 'BATCH_ACCEPTED' }),
    )
    expect(page).toEqual(
      getExample<AuditQueryResponse>('audit-query-batch-accepted'),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.items.every((item) => item.action === 'BATCH_ACCEPTED')).toBe(
      true,
    )
    expect(page.next_cursor).toBeNull()
  })

  it('issue: result=ISSUE → literal страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(mockFetch, auditQuery({ result: 'ISSUE' }))
    expect(page).toEqual(getExample<AuditQueryResponse>('audit-query-issue'))
    expectSchema('AuditQueryResponse', page)
    expect(page.items.every((item) => item.result === 'ISSUE')).toBe(true)
    expect(page.next_cursor).toBe('cursor-audit-issue-page2')
  })

  it('cursor-page2: известный курсор → literal вторая страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(
      mockFetch,
      auditQuery({ cursor: PAGE2_CURSOR }),
    )
    expect(page).toEqual(
      getExample<AuditQueryResponse>('audit-query-cursor-page2'),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.next_cursor).toBe('cursor-audit-primary-page3')
  })

  it('empty: окно после canned-дня → literal пустая страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(
      mockFetch,
      auditQuery({ from: EMPTY_FROM, to: EMPTY_TO }),
    )
    expect(page).toEqual(
      getExample<AuditQueryResponse>('audit-query-empty-window'),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.items).toEqual([])
    expect(page.next_cursor).toBeNull()
    expect(page.newest_event_id).toBeNull()
  })
})

describe('mock audit query: фильтры и валидация', () => {
  it('company: Atlas → day, Nova/неизвестная → пустая страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const atlas = await queryAs(mockFetch, auditQuery({ company_id: ATLAS }))
    expect(atlas.items.length).toBeGreaterThan(0)
    expect(atlas.items.every((item) => item.category === 'BUSINESS')).toBe(true)

    for (const companyId of [NOVA, 'company-does-not-exist']) {
      const empty = await queryAs(
        mockFetch,
        auditQuery({ company_id: companyId }),
      )
      expectSchema('AuditQueryResponse', empty)
      expect(empty.items).toEqual([])
      expect(empty.newest_event_id).toBeNull()
    }
  })

  it('actor_id: literal-отбор по автору страницы', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(
      mockFetch,
      auditQuery({ actor_id: 'user-demo-worker-2' }),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.items.length).toBeGreaterThan(0)
    expect(
      page.items.every((item) => item.actor?.user_id === 'user-demo-worker-2'),
    ).toBe(true)
  })

  it('query_text: регистронезависимая подстрока имени/пути', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(
      mockFetch,
      auditQuery({ query_text: 'batch-tech-quarantine' }),
    )
    expectSchema('AuditQueryResponse', page)
    expect(page.items.length).toBeGreaterThan(0)
    for (const item of page.items) {
      const haystack = [
        item.item_id,
        item.source?.relative_path,
        item.source?.display_path,
        item.target?.relative_path,
        item.target?.display_path,
      ]
        .filter((value): value is string => typeof value === 'string')
        .join(' ')
        .toLowerCase()
      expect(haystack).toContain('batch-tech-quarantine')
    }
  })

  it('прочие action/result: literal-отбор без выдуманных событий', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    const returned = await queryAs(
      mockFetch,
      auditQuery({ action: 'QUARANTINE_RETURNED' }),
    )
    expectSchema('AuditQueryResponse', returned)
    expect(returned.items.map((item) => item.event_id)).toEqual([
      'AUD-QR-RETURNED-SUCCESS',
    ])
    expect(returned.newest_event_id).toBe('AUD-QR-RETURNED-SUCCESS')
    expect(returned.next_cursor).toBeNull()

    // SYSTEM-событие FAILED доступно только ADMIN.
    const failed = await queryAs(mockFetch, auditQuery({ result: 'FAILED' }))
    expectSchema('AuditQueryResponse', failed)
    expect(failed.items.map((item) => item.event_id)).toEqual([
      'AUD-LOGIN-FAILED-KNOWN',
      'AUD-LOGIN-FAILED-ANONYMOUS',
    ])
    expect(failed.items.some((item) => item.actor === null)).toBe(true)

    const workerSetup = setup()
    await loginWithCsrf(workerSetup.api, 'auth-login-request-worker-one')
    const workerFailed = await queryAs(
      workerSetup.mockFetch,
      auditQuery({ result: 'FAILED' }),
    )
    expect(workerFailed.items).toEqual([])
  })

  it('невалидный интервал from>=to → 422 VALIDATION_ERROR (ORDER)', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    for (const body of [
      auditQuery({ from: DAY_TO, to: DAY_FROM }),
      auditQuery({ from: DAY_FROM, to: DAY_FROM }),
    ]) {
      const response = await mockFetch(queryRequest(body))
      expect(response.status).toBe(422)
      const error = await readError(response)
      expect(error.error.code).toBe('VALIDATION_ERROR')
      expect(error.error.message).toBe(
        getExample<ErrorResponse>('error-audit-validation').error.message,
      )
      expect(error.error.field_errors).toContainEqual(
        expect.objectContaining({ field: 'from', code: 'ORDER' }),
      )
      expectSchema('ErrorResponse', error)
    }
  })

  it('невалидный limit/схема тела → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    for (const limit of [0, 101, -1, 1.5]) {
      const response = await mockFetch(queryRequest(auditQuery({ limit })))
      expect(response.status).toBe(422)
      expect((await readError(response)).error.code).toBe('VALIDATION_ERROR')
    }

    const missing = await mockFetch(
      queryRequest({ from: DAY_FROM, to: DAY_TO }),
    )
    expect(missing.status).toBe(422)

    const extra = await mockFetch(
      queryRequest({ ...auditQuery(), extra: true }),
    )
    expect(extra.status).toBe(422)

    const broken = await mockFetch(
      request('/audit/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)
    expect((await readError(broken)).error.code).toBe('VALIDATION_ERROR')
  })

  it('чувствительные фильтры идут в теле POST, а не в URL', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const secret = 'quarterly-invoices'
    const req = queryRequest(
      auditQuery({ query_text: secret, actor_id: 'user-demo-worker-1' }),
    )
    expect(new URL(req.url).search).toBe('')
    expect(req.url).not.toContain(secret)

    const response = await mockFetch(req)
    expect(response.status).toBe(200)
  })
})

describe('mock audit query: роль и null actor', () => {
  it('WORKER видит только BUSINESS, без SYSTEM-событий', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-worker-one')

    const page = await queryAs(mockFetch, auditQuery({ limit: 100 }))
    expectSchema('AuditQueryResponse', page)
    expect(page.items.length).toBeGreaterThan(0)
    expect(page.items.every((item) => item.category === 'BUSINESS')).toBe(true)
    expect(page.items.some((item) => item.category === 'SYSTEM')).toBe(false)
  })

  it('ADMIN видит BUSINESS+SYSTEM и новейшее SYSTEM-событие', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    const page = await queryAs(mockFetch, auditQuery({ limit: 100 }))
    expectSchema('AuditQueryResponse', page)
    expect(page.items.some((item) => item.category === 'SYSTEM')).toBe(true)
    expect(page.newest_event_id).toBe(AUDIT_NEWEST_EVENT_ID)
    expect(page.items[0]?.event_id).toBe(AUDIT_NEWEST_EVENT_ID)

    // BUSINESS-события канонического дня сохранены literal.
    const businessIds = page.items
      .filter((item) => item.category === 'BUSINESS')
      .map((item) => item.event_id)
    expect(businessIds).toContain('AUD-QR-RETURN-RECOVERY')
  })

  it('null actor только у SYSTEM LOGIN_FAILED и не выдумывается', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    const page = await queryAs(mockFetch, auditQuery({ limit: 100 }))
    const nullActors = page.items.filter((item) => item.actor === null)
    expect(nullActors.length).toBeGreaterThan(0)
    for (const item of nullActors) {
      expect(item.category).toBe('SYSTEM')
      expect(item.action).toBe('LOGIN_FAILED')
    }
    // BUSINESS-событие всегда имеет автора.
    expect(
      page.items.some(
        (item) => item.category === 'BUSINESS' && item.actor === null,
      ),
    ).toBe(false)
  })
})

describe('mock audit updates', () => {
  it('after known → true literal; after newest → false', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    const known = await mockFetch(updatesRequest('AUD-LOGOUT-SYSTEM'))
    expect(known.status).toBe(200)
    const knownBody = await readJson<AuditUpdatesResponse>(known)
    expect(knownBody).toEqual(
      getExample<AuditUpdatesResponse>('audit-updates-after-known'),
    )
    expectSchema('AuditUpdatesResponse', knownBody)

    const newest = await mockFetch(updatesRequest(AUDIT_NEWEST_EVENT_ID))
    expect(newest.status).toBe(200)
    expect(await readJson<AuditUpdatesResponse>(newest)).toEqual({
      has_new_events: false,
    })
  })

  it('WORKER: новейшее доступное — BUSINESS, без SYSTEM', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-worker-one')

    const afterNewestBusiness = await mockFetch(
      updatesRequest(AUDIT_WORKER_NEWEST_EVENT_ID),
    )
    expect(
      await readJson<AuditUpdatesResponse>(afterNewestBusiness),
    ).toEqual({ has_new_events: false })

    const afterLogout = await mockFetch(updatesRequest('AUD-LOGOUT-SYSTEM'))
    expect(await readJson<AuditUpdatesResponse>(afterLogout)).toEqual({
      has_new_events: true,
    })
  })

  it('без after_event_id: непустой журнал → true, пустой → false', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    const nonEmpty = await mockFetch(updatesRequest(null))
    expect(await readJson<AuditUpdatesResponse>(nonEmpty)).toEqual({
      has_new_events: true,
    })

    controller.setAuditJournalEmpty(true)
    const empty = await mockFetch(updatesRequest(null))
    expect(await readJson<AuditUpdatesResponse>(empty)).toEqual({
      has_new_events: false,
    })
  })

  it('пустой/недопустимый after_event_id → 422; фильтры в URL не передаются', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    for (const invalidId of ['', '   ', 'bad id!']) {
      const invalid = await mockFetch(updatesRequest(invalidId))
      expect(invalid.status).toBe(422)
      const error = await readError(invalid)
      expect(error.error.code).toBe('VALIDATION_ERROR')
      expect(error.error.field_errors.some(
        (field) => field.field === 'after_event_id',
      )).toBe(true)
    }

    const req = updatesRequest('AUD-LOGOUT-SYSTEM')
    expect([...new URL(req.url).searchParams.keys()]).toEqual([
      'after_event_id',
    ])
  })
})

describe('mock audit actors', () => {
  it('literal audit-actors-atlas, включая заблокированного автора', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const response = await mockFetch(actorsRequest())
    expect(response.status).toBe(200)
    const page = await readJson<ActorPage>(response)
    expect(page).toEqual(getExample<ActorPage>(AUDIT_ACTORS_PAGE_ID))
    expectSchema('ActorPage', page)
    expect(page.items.map((actor) => actor.user_id)).toContain(
      'user-demo-worker-blocked',
    )
    expect(page.next_cursor).toBeNull()
  })

  it('prefix регистронезависим по login/display_name', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const lower = await readJson<ActorPage>(
      await mockFetch(actorsRequest({ prefix: 'worker' })),
    )
    expect(lower.items.map((actor) => actor.user_id)).toEqual([
      'user-demo-worker-1',
      'user-demo-worker-2',
    ])

    const upper = await readJson<ActorPage>(
      await mockFetch(actorsRequest({ prefix: 'WORKER' })),
    )
    expect(upper.items.map((actor) => actor.user_id)).toEqual([
      'user-demo-worker-1',
      'user-demo-worker-2',
    ])

    const blocked = await readJson<ActorPage>(
      await mockFetch(actorsRequest({ prefix: 'blocked' })),
    )
    expect(blocked.items.map((actor) => actor.user_id)).toEqual([
      'user-demo-worker-blocked',
    ])

    const unmatched = await readJson<ActorPage>(
      await mockFetch(actorsRequest({ prefix: 'zzz' })),
    )
    expect(unmatched.items).toEqual([])
    expect(unmatched.next_cursor).toBeNull()
  })

  it('cursor/limit: paging и 422 на невалидные значения', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const first = await readJson<ActorPage>(
      await mockFetch(actorsRequest({ limit: 1 })),
    )
    expect(first.items).toHaveLength(1)
    expect(first.next_cursor).toBe('audit-actors-offset-1')

    const second = await readJson<ActorPage>(
      await mockFetch(
        actorsRequest({ cursor: first.next_cursor ?? '', limit: 1 }),
      ),
    )
    expect(second.items).toHaveLength(1)
    expect(second.items[0].user_id).not.toBe(first.items[0].user_id)
    expect(second.next_cursor).toBe('audit-actors-offset-2')

    const badCursor = await mockFetch(
      actorsRequest({ cursor: 'unknown-cursor' }),
    )
    expect(badCursor.status).toBe(422)
    expect((await readError(badCursor)).error.code).toBe('VALIDATION_ERROR')

    for (const limit of [0, 101, -1]) {
      const bad = await mockFetch(actorsRequest({ limit }))
      expect(bad.status).toBe(422)
      expect((await readError(bad)).error.code).toBe('VALIDATION_ERROR')
    }
  })
})

describe('mock audit: связи literal ID', () => {
  it('recovery/return/batch/dictionary связи не выдумываются', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const page = await queryAs(mockFetch, auditQuery({ company_id: ATLAS }))
    const byId = new Map(page.items.map((item) => [item.event_id, item]))

    const recovery = byId.get('AUD-QR-RETURN-RECOVERY') as AuditEvent
    expect(recovery.operation_id).toBe(
      'return-atlas-batch-tech-quarantine-recovery',
    )
    expect(recovery.source_attempt_id).toBe(
      'attempt-batch-atlas-technical-batch-tech-quarantine',
    )
    expect(recovery.batch_id).toBe('batch-atlas-technical')
    expect(recovery.item_id).toBe('batch-tech-quarantine')
    expect(recovery.target).toBeNull()

    const returned = byId.get('AUD-QR-RETURNED-SUCCESS') as AuditEvent
    expect(returned.operation_id).toBe('return-atlas-batch-tech-quarantine')
    expect(returned.source_attempt_id).toBe(
      'attempt-batch-atlas-technical-batch-tech-quarantine',
    )

    const accepted = byId.get('audit-batch-atlas-technical-accepted') as AuditEvent
    expect(accepted.operation_id).toBe(accepted.batch_id)

    const published = byId.get('AUD-DICT-PUBLISH-ATLAS-GENERAL-V3') as AuditEvent
    expect(published.dictionary_id).toBe('dictionary-atlas-general')
    expect(published.version_id).toBe('version-atlas-general-v3')
    expect(published.rule_set_id).toBe('rule-set-atlas-v3')

    const attempt = byId.get(
      'audit-attempt-batch-atlas-technical-batch-tech-quarantine-finished',
    ) as AuditEvent
    expect(attempt.attempt_id).toBe(
      'attempt-batch-atlas-technical-batch-tech-quarantine',
    )
    expect(attempt.item_id).toBe('batch-tech-quarantine')
    expect(attempt.operation_id).toBe(attempt.attempt_id)
  })
})

describe('mock audit: 401/403/422 и управляемые ошибки', () => {
  it('без сессии все три операции → 401 UNAUTHENTICATED', async () => {
    const { mockFetch } = setup()

    for (const req of [
      queryRequest(auditQuery()),
      updatesRequest(AUDIT_NEWEST_EVENT_ID),
      actorsRequest(),
    ]) {
      const response = await mockFetch(req)
      expect(response.status).toBe(401)
      expect((await readError(response)).error.code).toBe('UNAUTHENTICATED')
    }
  })

  it('setError/failNext/clearError по объявленным кодам', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')

    controller.setError('queryAuditEvents', 'SERVICE_UNAVAILABLE')
    const unavailable = await mockFetch(queryRequest(auditQuery()))
    expect(unavailable.status).toBe(503)
    const unavailableError = await readError(unavailable)
    expect(unavailableError.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(unavailableError.error.retryable).toBe(true)
    expectSchema('ErrorResponse', unavailableError)
    controller.clearError('queryAuditEvents')

    controller.setError('listAuditActors', 'RATE_LIMITED')
    const limited = await mockFetch(actorsRequest())
    expect(limited.status).toBe(429)
    expect((await readError(limited)).error.code).toBe('RATE_LIMITED')
    controller.clearError('listAuditActors')

    controller.failNext('getAuditUpdates', 'FORBIDDEN')
    const forbidden = await mockFetch(updatesRequest(AUDIT_NEWEST_EVENT_ID))
    expect(forbidden.status).toBe(403)
    expect((await readError(forbidden)).error.code).toBe('FORBIDDEN')

    const recovered = await mockFetch(updatesRequest(AUDIT_NEWEST_EVENT_ID))
    expect(recovered.status).toBe(200)
  })

  it('per-operation ограничение и runtime-guard undeclared кода', async () => {
    expect(AUDIT_SCENARIOS).toEqual([
      'day',
      'issue',
      'batch-accepted',
      'cursor-page2',
      'empty',
    ])
    for (const operation of [
      'queryAuditEvents',
      'getAuditUpdates',
      'listAuditActors',
    ] as const) {
      expect(auditErrorCodesByOperation[operation]).not.toContain('CSRF_FAILED')
      expect(auditErrorCodesByOperation[operation]).not.toContain('NOT_FOUND')
      expect(
        isAuditErrorDeclaredForOperation(operation, 'SERVICE_UNAVAILABLE'),
      ).toBe(true)
    }
    expect(declaredAuditErrors.VALIDATION_ERROR.exampleId).toBe(
      'error-validation-error',
    )
    expect(declaredAuditErrors.SERVICE_UNAVAILABLE.exampleId).toBeNull()

    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api, 'auth-login-request-admin')
    const rawSetError = controller.setError.bind(controller) as unknown as (
      operation: string,
      code: MockAuditErrorCode,
    ) => void
    rawSetError('queryAuditEvents', 'NOT_FOUND' as MockAuditErrorCode)
    const ignored = await mockFetch(queryRequest(auditQuery()))
    expect(ignored.status).toBe(200)
    controller.clearError('queryAuditEvents')
  })
})

describe('mock audit: reset', () => {
  it('reset очищает сценарий, пустой журнал и управляемые ошибки', async () => {
    const { api, controller, mockFetch } = setup()
    controller.setAuditScenario('empty')
    controller.setAuditJournalEmpty(true)
    controller.setError('queryAuditEvents', 'RATE_LIMITED')

    controller.reset()

    expect(controller.getAuditScenario()).toBeNull()
    expect(controller.isAuditJournalEmpty()).toBe(false)
    expect(controller.getAuditStore().getScenario()).toBeNull()

    resetSessionContext()
    await loginWithCsrf(api, 'auth-login-request-admin')
    const page = await mockFetch(queryRequest(auditQuery({ limit: 100 })))
    expect(page.status).toBe(200)
    const updates = await mockFetch(updatesRequest(null))
    expect(await readJson<AuditUpdatesResponse>(updates)).toEqual({
      has_new_events: true,
    })
  })

  it('setAuditScenario выбирает canned-страницу напрямую', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)

    for (const [scenario, exampleId] of [
      ['issue', 'audit-query-issue'],
      ['batch-accepted', 'audit-query-batch-accepted'],
      ['cursor-page2', 'audit-query-cursor-page2'],
      ['empty', 'audit-query-empty-window'],
      ['day', 'audit-query-day-atlas'],
    ] as const) {
      controller.setAuditScenario(scenario)
      const page = await queryAs(mockFetch, auditQuery({ company_id: ATLAS }))
      expect(page).toEqual(getExample<AuditQueryResponse>(exampleId))
      expectSchema('AuditQueryResponse', page)
    }
  })
})
