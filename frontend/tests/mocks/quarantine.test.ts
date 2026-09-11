// LT-07.3a: контрактные mocks карантина/возврата
// (`listQuarantineItems`/`returnQuarantineItem`) без реального возврата,
// recovery, перемещения файлов и автосортировки.
//
// Проверки идут через `createApiClient({ mode: 'mock', fetch })` (тот же
// транспорт/CSRF/идемпотентность/error-модель, что и real) и через mock-fetch
// напрямую для явного `Idempotency-Key` и невалидных запросов. Все успешные и
// ошибочные ответы дополнительно валидируются по схемам OAS.
//
// Карантин отдаёт literal canned-данные из
// `contracts/examples/quarantine/*.json`: подтверждённый список, can_return/
// recovery, успешный возврат WAITING_READY, все объявленные конфликты,
// идемпотентный replay/lost response и позднее состояние списка. Второй
// перемещение/партия не создаются.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  QUARANTINE_COMPANY_ID,
  QUARANTINE_ID,
  QUARANTINE_RECOVERY_OPERATION_ID,
  QUARANTINE_SCENARIOS,
  declaredQuarantineErrors,
  isQuarantineErrorDeclaredForOperation,
  quarantineErrorCodesByOperation,
} from '@/mocks'
import {
  createMockFetch,
  MockController,
  type MockFetch,
  type MockQuarantineErrorCode,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { matchMockRoute } from '@/mocks/router'
import type {
  ErrorResponse,
  LoginRequest,
  QuarantineItem,
  QuarantinePage,
  QuarantineReturnRequest,
  QuarantineReturnResponse,
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

const ATLAS = QUARANTINE_COMPANY_ID
const NOVA = 'company-demo-nova'

const KEY_SUCCESS = '11111111-1111-4111-8111-111111111111'
const KEY_REUSE = '22222222-2222-4222-8222-222222222222'
const KEY_NEW = '33333333-3333-4333-8333-333333333333'
const KEY_RECOVERY = '44444444-4444-4444-8444-444444444444'

const VALID_COMMENT = 'Повторно проверить после устранения ошибки.'

function returnBody(
  expectedRevision: number,
  comment = VALID_COMMENT,
): QuarantineReturnRequest {
  return { expected_revision: expectedRevision, comment }
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
  return request(`/quarantine${suffix}`)
}

interface RawReturnOptions {
  csrfToken?: string | null
  idempotencyKey?: string
}

/** Сырой POST return с явным CSRF/Idempotency-Key (для replay/reuse). */
function returnRequest(
  quarantineId: string,
  body: unknown,
  options: RawReturnOptions = {},
): Request {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.csrfToken !== null) {
    headers['X-CSRF-Token'] = options.csrfToken ?? 'caller-placeholder'
  }
  if (options.idempotencyKey !== undefined) {
    headers['Idempotency-Key'] = options.idempotencyKey
  }
  return request(`/quarantine/${quarantineId}/return`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
}

/** Выполняет успешный возврат и возвращает literal-ответ. */
async function performSuccess(
  mockFetch: MockFetch,
  csrfToken: string,
  key = KEY_SUCCESS,
): Promise<QuarantineReturnResponse> {
  const response = await mockFetch(
    returnRequest(QUARANTINE_ID, returnBody(1), {
      csrfToken,
      idempotencyKey: key,
    }),
  )
  expect(response.status).toBe(200)
  return readJson<QuarantineReturnResponse>(response)
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация карантина', () => {
  it('регистрирует list/return и извлекает quarantine_id', () => {
    const list = matchMockRoute('GET', '/quarantine')
    expect(list).toBeDefined()
    expect(list?.params).toEqual({})

    const ret = matchMockRoute(
      'POST',
      `/quarantine/${QUARANTINE_ID}/return`,
    )
    expect(ret).toBeDefined()
    expect(ret?.params).toEqual({ quarantine_id: QUARANTINE_ID })
  })

  it('ответы несут X-Request-ID, Cache-Control и mock-маркер', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const list = await mockFetch(listRequest(ATLAS))
    expect(list.status).toBe(200)
    expect(list.headers.get('Cache-Control')).toBe('no-store')
    expect(list.headers.get('X-Request-ID')).toMatch(/^request-mock-\d+$/)
    expect(list.headers.get('X-WiseWay-Mock')).toBe('mock')

    const ret = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(ret.status).toBe(200)
    expect(ret.headers.get('X-WiseWay-Mock')).toBe('mock')
  })
})

describe('mock quarantine: list — literal, company-scope, paging', () => {
  it('Atlas → 200 literal quarantine-list-atlas (только confirmed)', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const response = await mockFetch(listRequest(ATLAS))
    expect(response.status).toBe(200)
    const page = await readJson<QuarantinePage>(response)
    expect(page).toEqual(getExample<QuarantinePage>('quarantine-list-atlas'))
    expectSchema('QuarantinePage', page)
    expect(page.items).toHaveLength(1)
    const item = page.items[0]
    expect(item.quarantine_id).toBe(QUARANTINE_ID)
    expect(item.reason_code).toBe('TECHNICAL_ERROR')
    expect(item.can_return).toBe(true)
    expect(item.recovery_operation_id).toBeNull()
    // RECOVERY_REQUIRED-исходы партии не входят в подтверждённый список.
    expect(page.items.some((entry) => entry.item_id.includes('recovery'))).toBe(
      false,
    )
  })

  it('неизвестная компания → пустая страница', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const response = await mockFetch(listRequest(NOVA))
    expect(response.status).toBe(200)
    const page = await readJson<QuarantinePage>(response)
    expectSchema('QuarantinePage', page)
    expect(page.items).toHaveLength(0)
    expect(page.next_cursor).toBeNull()
  })

  it('paging/cursor: limit=1 и quarantine-offset-0; неизвестный cursor → 422', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    const limited = await mockFetch(listRequest(ATLAS, { limit: 1 }))
    expect(limited.status).toBe(200)
    const limitedPage = await readJson<QuarantinePage>(limited)
    expect(limitedPage.items).toHaveLength(1)
    expect(limitedPage.next_cursor).toBeNull()

    const offset = await mockFetch(
      listRequest(ATLAS, { cursor: 'quarantine-offset-0', limit: 1 }),
    )
    expect(offset.status).toBe(200)
    const offsetPage = await readJson<QuarantinePage>(offset)
    expect(offsetPage.items).toHaveLength(1)
    expect(offsetPage.next_cursor).toBeNull()

    const beyond = await mockFetch(
      listRequest(ATLAS, { cursor: 'quarantine-offset-5' }),
    )
    expect(beyond.status).toBe(200)
    expect((await readJson<QuarantinePage>(beyond)).items).toHaveLength(0)

    const bad = await mockFetch(listRequest(ATLAS, { cursor: 'unknown-cursor' }))
    expect(bad.status).toBe(422)
    const error = await readError(bad)
    expect(error.error.code).toBe('VALIDATION_ERROR')
    expectSchema('ErrorResponse', error)
  })

  it('невалидный limit и отсутствие company_id → 422', async () => {
    const { api, mockFetch } = setup()
    await loginWithCsrf(api)

    for (const limit of [0, 101, -1, 1.5]) {
      const response = await mockFetch(listRequest(ATLAS, { limit }))
      expect(response.status).toBe(422)
      const error = await readError(response)
      expect(error.error.code).toBe('VALIDATION_ERROR')
      expect(error.error.field_errors.some((f) => f.field === 'limit')).toBe(true)
    }

    const missing = await mockFetch(listRequest(null))
    expect(missing.status).toBe(422)
    const missingError = await readError(missing)
    expect(missingError.error.code).toBe('VALIDATION_ERROR')
    expect(
      missingError.error.field_errors.some((f) => f.field === 'company_id'),
    ).toBe(true)
  })

  it('can_return/recovery: ambiguous → can_return=false с recovery_operation_id', async () => {
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    controller.setQuarantineScenario('ambiguous')
    expect(controller.getQuarantineCanReturn()).toBe(false)

    const response = await mockFetch(listRequest(ATLAS))
    expect(response.status).toBe(200)
    const page = await readJson<QuarantinePage>(response)
    expectSchema('QuarantinePage', page)
    expect(page.items).toHaveLength(1)
    const item = page.items[0]
    expect(item.can_return).toBe(false)
    expect(item.recovery_operation_id).toBe(QUARANTINE_RECOVERY_OPERATION_ID)
    expect(item.revision).toBe(3)

    // Управление can_return возвращает возвратимое состояние.
    controller.setQuarantineCanReturn(true)
    expect(controller.getQuarantineCanReturn()).toBe(true)
    const technical = await readJson<QuarantinePage>(
      await mockFetch(listRequest(ATLAS)),
    )
    expect(technical.items[0].can_return).toBe(true)
    expect(technical.items[0].recovery_operation_id).toBeNull()
  })

  it('list без сессии → 401 UNAUTHENTICATED', async () => {
    const { mockFetch } = setup()
    const response = await mockFetch(listRequest(ATLAS))
    expect(response.status).toBe(401)
    expect((await readError(response)).error.code).toBe('UNAUTHENTICATED')
  })
})

describe('mock quarantine: return success', () => {
  it('200 literal quarantine-return-response: WAITING_READY, не selectable, без batch', async () => {
    const { api, controller, calls, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const response = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(response.status).toBe(200)
    const result = await readJson<QuarantineReturnResponse>(response)
    expect(result).toEqual(
      getExample<QuarantineReturnResponse>('quarantine-return-response'),
    )
    expectSchema('QuarantineReturnResponse', result)
    expect(result.return_operation_id).toBe('return-atlas-batch-tech-quarantine')
    expect(result.item.status).toBe('WAITING_READY')
    expect(result.item.selectable).toBe(false)
    expect(result.item.active_attempt_id).toBeNull()
    expect(result.item.reason_code).toBeNull()
    expect(result.item.source).toEqual(
      getExample<QuarantineItem>('quarantine-item-atlas-technical')
        .original_location,
    )

    expect(controller.getQuarantineStore().isReturned()).toBe(true)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(1)
    // Возврат не создаёт batch и не запускает автосортировку.
    expect(
      calls.some((call) => call.startsWith('POST /api/v1/sorting/batches')),
    ).toBe(false)
  })

  it('typed client: транспорт добавляет CSRF и Idempotency-Key', async () => {
    const { api } = setup()
    await loginWithCsrf(api)

    const result = await api.POST('/quarantine/{quarantine_id}/return', {
      params: {
        path: { quarantine_id: QUARANTINE_ID },
        header: {
          'X-CSRF-Token': 'caller-placeholder',
          'Idempotency-Key': '00000000-0000-4000-8000-000000000000',
        },
      },
      body: returnBody(1),
    })
    expect(result.response.status).toBe(200)
    expect(result.data?.return_operation_id).toBe(
      'return-atlas-batch-tech-quarantine',
    )
    expect(result.data?.item.status).toBe('WAITING_READY')
  })

  it('границы comment: 0/501 → 422, 1/500 → 200, без мутаций на отказе', async () => {
    const short = setup()
    const shortSession = await loginWithCsrf(short.api)
    const zero = await short.mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1, ''), {
        csrfToken: shortSession.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(zero.status).toBe(422)
    const zeroError = await readError(zero)
    expect(zeroError.error.code).toBe('VALIDATION_ERROR')
    expect(zeroError.error.field_errors.some((f) => f.field === 'comment')).toBe(
      true,
    )
    expectSchema('ErrorResponse', zeroError)

    const long = setup()
    const longSession = await loginWithCsrf(long.api)
    const tooLong = await long.mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1, 'a'.repeat(501)), {
        csrfToken: longSession.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(tooLong.status).toBe(422)
    expect((await readError(tooLong)).error.field_errors.some(
      (f) => f.field === 'comment',
    )).toBe(true)
    // Отклонённый запрос ничего не мутирует.
    expect(long.controller.getQuarantineStore().getReturnCount()).toBe(0)
    expect(
      (
        await readJson<QuarantinePage>(
          await long.mockFetch(listRequest(ATLAS)),
        )
      ).items,
    ).toHaveLength(1)

    const one = setup()
    const oneSession = await loginWithCsrf(one.api)
    expect(
      (
        await one.mockFetch(
          returnRequest(QUARANTINE_ID, returnBody(1, 'x'), {
            csrfToken: oneSession.csrf_token,
            idempotencyKey: KEY_SUCCESS,
          }),
        )
      ).status,
    ).toBe(200)

    const full = setup()
    const fullSession = await loginWithCsrf(full.api)
    expect(
      (
        await full.mockFetch(
          returnRequest(QUARANTINE_ID, returnBody(1, 'b'.repeat(500)), {
            csrfToken: fullSession.csrf_token,
            idempotencyKey: KEY_SUCCESS,
          }),
        )
      ).status,
    ).toBe(200)
  })
})

describe('mock quarantine: return conflicts', () => {
  it('неизвестный quarantine_id → 404 NOT_FOUND', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const response = await mockFetch(
      returnRequest('quarantine-does-not-exist', returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(response.status).toBe(404)
    const error = await readError(response)
    expect(error.error.code).toBe('NOT_FOUND')
    expectSchema('ErrorResponse', error)
  })

  it('уже возвращённая запись с новым ключом → 409 INVALID_STATE', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    controller.setQuarantineScenario('returned')

    const response = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(2), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_NEW,
      }),
    )
    expect(response.status).toBe(409)
    const error = await readError(response)
    expect(error.error.code).toBe('INVALID_STATE')
    expectSchema('ErrorResponse', error)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
  })

  it('устаревшая expected_revision → 409 QUARANTINE_VERSION_CONFLICT', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const response = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(0), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(response.status).toBe(409)
    const error = await readError(response)
    expect(error.error.code).toBe('QUARANTINE_VERSION_CONFLICT')
    expectSchema('ErrorResponse', error)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
  })

  it('занятый исходный путь → 409 ORIGINAL_PATH_OCCUPIED без мутаций', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    controller.setQuarantineGate('ORIGINAL_PATH_OCCUPIED')

    const response = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(response.status).toBe(409)
    const error = await readError(response)
    expect(error.error.code).toBe('ORIGINAL_PATH_OCCUPIED')
    expectSchema('ErrorResponse', error)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
    const page = await readJson<QuarantinePage>(
      await mockFetch(listRequest(ATLAS)),
    )
    expect(page.items).toHaveLength(1)
  })

  it('ambiguous → 409 RECOVERY_REQUIRED с error.operation_id', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    controller.setQuarantineScenario('ambiguous')

    const response = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(3), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_RECOVERY,
      }),
    )
    expect(response.status).toBe(409)
    const error = await readError(response)
    expect(error.error.code).toBe('RECOVERY_REQUIRED')
    expect(error.error.operation_id).toBe(QUARANTINE_RECOVERY_OPERATION_ID)
    expect(error.error.retryable).toBe(false)
    expectSchema('ErrorResponse', error)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
  })

  it('тот же ключ с другим телом → 409 IDEMPOTENCY_KEY_REUSED', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await performSuccess(mockFetch, session.csrf_token, KEY_REUSE)

    const reused = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1, 'Изменённое тело.'), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_REUSE,
      }),
    )
    expect(reused.status).toBe(409)
    const error = await readError(reused)
    expect(error.error.code).toBe('IDEMPOTENCY_KEY_REUSED')
    expectSchema('ErrorResponse', error)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(1)
  })
})

describe('mock quarantine: идемпотентность', () => {
  it('replay success: same key+body → тот же ответ, без второго перемещения', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const first = await performSuccess(mockFetch, session.csrf_token)
    const replay = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(replay.status).toBe(200)
    expect(await readJson<QuarantineReturnResponse>(replay)).toEqual(first)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(1)
  })

  it('replay recovery: same key+body → тот же 409 с прежним operation_id', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    controller.setQuarantineScenario('ambiguous')

    const first = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(3), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_RECOVERY,
      }),
    )
    expect(first.status).toBe(409)
    const firstError = await readError(first)

    const replay = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(3), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_RECOVERY,
      }),
    )
    expect(replay.status).toBe(409)
    const replayError = await readError(replay)
    expect(replayError.error.code).toBe('RECOVERY_REQUIRED')
    expect(replayError.error.operation_id).toBe(firstError.error.operation_id)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
  })

  it('новый key после успеха → новая операция по текущему состоянию (INVALID_STATE)', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await performSuccess(mockFetch, session.csrf_token, KEY_SUCCESS)

    const withNewKey = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_NEW,
      }),
    )
    expect(withNewKey.status).toBe(409)
    expect((await readError(withNewKey)).error.code).toBe('INVALID_STATE')
    expect(controller.getQuarantineStore().getReturnCount()).toBe(1)
  })

  it('user-scope: тот же ключ у другого пользователя — отдельный scope', async () => {
    const { api, mockFetch } = setup()
    const workerOne = await loginWithCsrf(api, 'auth-login-request-worker-one')
    await performSuccess(mockFetch, workerOne.csrf_token, KEY_SUCCESS)

    const workerTwo = await loginWithCsrf(api, 'auth-login-request-worker-two')
    const scoped = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(2), {
        csrfToken: workerTwo.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(scoped.status).toBe(409)
    const error = await readError(scoped)
    // Не глобальный конфликт ключа, а оценка текущего состояния.
    expect(error.error.code).toBe('INVALID_STATE')
  })
})

describe('mock quarantine: 401/403/404/422 и управляемые ошибки', () => {
  it('return без сессии → 401; без/с неверным CSRF → 403, без мутаций', async () => {
    const anon = setup()
    const noSession = await anon.mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: 'x',
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(noSession.status).toBe(401)
    expect((await readError(noSession)).error.code).toBe('UNAUTHENTICATED')

    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    const noToken = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: null,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(noToken.status).toBe(403)
    expect((await readError(noToken)).error.code).toBe('CSRF_FAILED')

    const wrong = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: `${session.csrf_token}-wrong`,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(wrong.status).toBe(403)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)
  })

  it('невалидное тело и отсутствие Idempotency-Key → 422 без успеха', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    const missingRevision = await mockFetch(
      returnRequest(
        QUARANTINE_ID,
        { comment: VALID_COMMENT },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_SUCCESS },
      ),
    )
    expect(missingRevision.status).toBe(422)
    expect((await readError(missingRevision)).error.code).toBe(
      'VALIDATION_ERROR',
    )

    const extraField = await mockFetch(
      returnRequest(
        QUARANTINE_ID,
        { expected_revision: 1, comment: VALID_COMMENT, extra: true },
        { csrfToken: session.csrf_token, idempotencyKey: KEY_SUCCESS },
      ),
    )
    expect(extraField.status).toBe(422)

    const broken = await mockFetch(
      request(`/quarantine/${QUARANTINE_ID}/return`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrf_token,
          'Idempotency-Key': KEY_SUCCESS,
        },
        body: '{not-json',
      }),
    )
    expect(broken.status).toBe(422)

    const noKey = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
      }),
    )
    expect(noKey.status).toBe(422)
    const noKeyError = await readError(noKey)
    expect(
      noKeyError.error.field_errors.some((f) => f.field === 'Idempotency-Key'),
    ).toBe(true)
  })

  it('setError/failNext/clearError по объявленным кодам', async () => {
    const { api, controller, mockFetch } = setup()
    const session = await loginWithCsrf(api)

    controller.setError('returnQuarantineItem', 'INVALID_STATE')
    const conflict = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: session.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(conflict.status).toBe(409)
    expect((await readError(conflict)).error.code).toBe('INVALID_STATE')
    controller.clearError('returnQuarantineItem')

    controller.failNext('listQuarantineItems', 'SERVICE_UNAVAILABLE')
    const first = await mockFetch(listRequest(ATLAS))
    expect(first.status).toBe(503)
    const error = await readError(first)
    expect(error.error.code).toBe('SERVICE_UNAVAILABLE')
    expect(error.error.retryable).toBe(true)
    expect(error.error.operation_id).toBeNull()
    expect(error.error.field_errors).toEqual([])
    expectSchema('ErrorResponse', error)

    const second = await mockFetch(listRequest(ATLAS))
    expect(second.status).toBe(200)

    controller.failNext('listQuarantineItems', 'RATE_LIMITED')
    const limited = await mockFetch(listRequest(ATLAS))
    expect(limited.status).toBe(429)
    expect((await readError(limited)).error.code).toBe('RATE_LIMITED')
  })

  it('per-operation ограничение и runtime-guard undeclared кода', async () => {
    expect(
      isQuarantineErrorDeclaredForOperation(
        'listQuarantineItems',
        'RECOVERY_REQUIRED',
      ),
    ).toBe(false)
    expect(
      isQuarantineErrorDeclaredForOperation('listQuarantineItems', 'NOT_FOUND'),
    ).toBe(false)
    expect(
      isQuarantineErrorDeclaredForOperation(
        'returnQuarantineItem',
        'RECOVERY_REQUIRED',
      ),
    ).toBe(true)
    expect(quarantineErrorCodesByOperation.listQuarantineItems).not.toContain(
      'NOT_FOUND',
    )
    expect(declaredQuarantineErrors.RECOVERY_REQUIRED.exampleId).toBe(
      'error-quarantine-recovery-required',
    )

    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)
    const rawSetError = controller.setError.bind(controller) as unknown as (
      operation: string,
      code: MockQuarantineErrorCode,
    ) => void
    rawSetError('listQuarantineItems', 'NOT_FOUND' as MockQuarantineErrorCode)
    const ignored = await mockFetch(listRequest(ATLAS))
    expect(ignored.status).toBe(200)
    controller.clearError('listQuarantineItems')
  })
})

describe('mock quarantine: late response и reset', () => {
  it('после возврата список отражает обновлённое состояние (пусто)', async () => {
    const { api, mockFetch } = setup()
    const session = await loginWithCsrf(api)
    await performSuccess(mockFetch, session.csrf_token)

    const after = await mockFetch(listRequest(ATLAS))
    expect(after.status).toBe(200)
    const page = await readJson<QuarantinePage>(after)
    expectSchema('QuarantinePage', page)
    expect(page.items).toHaveLength(0)
    expect(page.next_cursor).toBeNull()
  })

  it('reset очищает сценарий/gate/store/errors', async () => {
    const { api, controller, mockFetch } = setup()
    controller.setQuarantineScenario('ambiguous')
    controller.setQuarantineGate('ORIGINAL_PATH_OCCUPIED')
    controller.setError('listQuarantineItems', 'RATE_LIMITED')

    controller.reset()

    expect(controller.getQuarantineScenario()).toBe('technical')
    expect(controller.getQuarantineGate()).toBeNull()
    expect(controller.getQuarantineCanReturn()).toBe(true)
    expect(controller.getQuarantineStore().isReturned()).toBe(false)
    expect(controller.getQuarantineStore().getReturnCount()).toBe(0)

    resetSessionContext()
    const newSession = await loginWithCsrf(api)
    const list = await mockFetch(listRequest(ATLAS))
    expect(list.status).toBe(200)
    expect((await readJson<QuarantinePage>(list)).items).toHaveLength(1)

    const ret = await mockFetch(
      returnRequest(QUARANTINE_ID, returnBody(1), {
        csrfToken: newSession.csrf_token,
        idempotencyKey: KEY_SUCCESS,
      }),
    )
    expect(ret.status).toBe(200)
  })

  it('все объявленные состояния карантина разрешаются в schema-valid данные', async () => {
    expect(QUARANTINE_SCENARIOS).toEqual([
      'technical',
      'ambiguous',
      'returned',
    ])
    const { api, controller, mockFetch } = setup()
    await loginWithCsrf(api)

    controller.setQuarantineScenario('technical')
    expectSchema('QuarantinePage', await readJson(
      await mockFetch(listRequest(ATLAS)),
    ))
    controller.setQuarantineScenario('ambiguous')
    const ambiguous = await readJson<QuarantinePage>(
      await mockFetch(listRequest(ATLAS)),
    )
    expectSchema('QuarantinePage', ambiguous)
    expect(ambiguous.items[0].can_return).toBe(false)
    controller.setQuarantineScenario('returned')
    const returned = await readJson<QuarantinePage>(
      await mockFetch(listRequest(ATLAS)),
    )
    expect(returned.items).toHaveLength(0)
  })
})
