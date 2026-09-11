// LT-06.1: контрактные mocks bootstrap/session/config без backend.
//
// Проверки идут двумя путями: через `createApiClient({ mode: 'mock', fetch })`
// (тот же транспорт/CSRF/error-модель, что и real) и через mock-fetch напрямую
// для невалидных/неизвестных запросов, которые типизированный клиент не
// позволяет собрать. Все ответы дополнительно валидируются по схемам OAS.

import { beforeEach, describe, expect, it } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  createMockFetch,
  MOCK_MARKER_HEADER,
  MOCK_MODE,
  MockController,
  type MockFetch,
} from '@/mocks'
import { getExample } from '@/mocks/data'
import { findMockHandler } from '@/mocks/router'
import type {
  AppConfig,
  CompaniesResponse,
  ErrorResponse,
  LoginRequest,
  RootsResponse,
  Session,
} from '@/mocks/types'
import { validateSchema } from '@/mocks/validate'

interface Setup {
  controller: MockController
  mockFetch: MockFetch
  api: WiseWayApiClient
  sleeps: number[]
}

function setup(): Setup {
  const sleeps: number[] = []
  const controller = new MockController({
    sleep: async (ms) => {
      sleeps.push(ms)
    },
  })
  const mockFetch = createMockFetch(controller)
  const api = createApiClient({
    mode: 'mock',
    baseUrl: 'http://localhost/api/v1',
    fetch: mockFetch,
  })
  return { controller, mockFetch, api, sleeps }
}

function request(path: string, init?: RequestInit): Request {
  return new Request(`http://localhost/api/v1${path}`, init)
}

async function readError(response: Response): Promise<ErrorResponse> {
  return (await response.json()) as ErrorResponse
}

async function loginWorkerOne(api: WiseWayApiClient): Promise<Session> {
  const body = getExample<LoginRequest>('auth-login-request-worker-one')
  const result = await api.POST('/auth/login', { body })
  expect(result.response.status).toBe(200)
  if (!result.data) {
    throw new Error('login не вернул Session')
  }
  return result.data
}

// Generated-тип logout требует обязательный header-параметр X-CSRF-Token.
// Транспорт — единственный источник mutation-заголовков: он подставляет токен
// из session-context либо удаляет заголовок, если токена нет, поэтому значение
// заглушки здесь ни на что не влияет.
function postLogout(api: WiseWayApiClient) {
  return api.POST('/auth/logout', {
    params: { header: { 'X-CSRF-Token': 'caller-placeholder' } },
  })
}

beforeEach(() => {
  resetSessionContext()
})

describe('mock-fetch: маршрутизация и контракт', () => {
  it('регистрирует ровно 7 операций bootstrap/session/config', () => {
    const routes = [
      ['GET', '/health'],
      ['POST', '/auth/login'],
      ['GET', '/session'],
      ['POST', '/auth/logout'],
      ['GET', '/app-config'],
      ['GET', '/roots'],
      ['GET', '/companies'],
    ] as const
    for (const [method, path] of routes) {
      expect(findMockHandler(method, path), `${method} ${path}`).toBeDefined()
    }
  })

  it('getHealth → 200 {status:ok} без сессии и с контрактными заголовками', async () => {
    const { api } = setup()
    const result = await api.GET('/health')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual({ status: 'ok' })
    expect(result.response.headers.get('Content-Type')).toContain(
      'application/json',
    )
    expect(result.response.headers.get('Cache-Control')).toBe('no-store')
    expect(result.response.headers.get('X-Request-ID')).toMatch(
      /^request-mock-\d+$/,
    )
    expect(result.response.headers.get(MOCK_MARKER_HEADER)).toBe(MOCK_MODE)
    expect(validateSchema('HealthResponse', result.data).valid).toBe(true)
  })

  it('неизвестный маршрут → 404 NOT_FOUND без правдоподобного успеха', async () => {
    const { mockFetch } = setup()
    const response = await mockFetch(request('/unknown'))

    expect(response.status).toBe(404)
    const body = await readError(response)
    expect(body.error.code).toBe('NOT_FOUND')
    expect(body.error.request_id).toBe(response.headers.get('X-Request-ID'))
    expect(validateSchema('ErrorResponse', body).valid).toBe(true)
  })

  it('неизвестный метод на известном пути → 404', async () => {
    const { mockFetch } = setup()
    const response = await mockFetch(request('/health', { method: 'DELETE' }))
    expect(response.status).toBe(404)
  })
})

describe('mock-fetch: login и сессия', () => {
  const cases = [
    ['auth-login-request-worker-one', 'auth-session-worker-one'],
    ['auth-login-request-worker-two', 'auth-session-worker-two'],
    ['auth-login-request-admin', 'auth-session-admin'],
  ] as const

  it.each(cases)(
    'login по примеру %s → 200 %s и активная mock-сессия',
    async (loginExampleId, sessionExampleId) => {
      const { api, controller } = setup()
      const loginRequest = getExample<LoginRequest>(loginExampleId)
      const expected = getExample<Session>(sessionExampleId)

      const result = await api.POST('/auth/login', { body: loginRequest })

      expect(result.response.status).toBe(200)
      expect(result.data).toEqual(expected)
      expect(controller.getSession()).toEqual(expected)
      expect(validateSchema('Session', result.data).valid).toBe(true)
    },
  )

  it('неверный пароль → 401 LOGIN_FAILED и сессия не создаётся', async () => {
    const { api, controller } = setup()
    const result = await api.POST('/auth/login', {
      body: { login: 'worker.one', password: 'wrong-password' },
    })

    expect(result.response.status).toBe(401)
    expect(result.error?.error.code).toBe('LOGIN_FAILED')
    expect(controller.isAuthenticated()).toBe(false)
    expect(validateSchema('ErrorResponse', result.error).valid).toBe(true)
  })

  it('getSession до login → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const result = await api.GET('/session')

    expect(result.response.status).toBe(401)
    expect(result.error?.error.code).toBe('UNAUTHENTICATED')
    expect(validateSchema('ErrorResponse', result.error).valid).toBe(true)
  })

  it('getSession после login → 200 та же Session', async () => {
    const { api } = setup()
    const session = await loginWorkerOne(api)

    const result = await api.GET('/session')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(session)
    expect(validateSchema('Session', result.data).valid).toBe(true)
  })

  it('logout с корректным CSRF → 204, затем getSession → 401', async () => {
    const { api, controller } = setup()
    const session = await loginWorkerOne(api)
    setCsrfToken(session.csrf_token)

    const logout = await postLogout(api)

    expect(logout.response.status).toBe(204)
    expect(controller.isAuthenticated()).toBe(false)

    const after = await api.GET('/session')
    expect(after.response.status).toBe(401)
    expect(after.error?.error.code).toBe('UNAUTHENTICATED')
  })

  it('logout без CSRF → 403 CSRF_FAILED, сессия сохраняется', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)

    const logout = await postLogout(api)

    expect(logout.response.status).toBe(403)
    expect(logout.error?.error.code).toBe('CSRF_FAILED')
    expect(controller.isAuthenticated()).toBe(true)
    expect(validateSchema('ErrorResponse', logout.error).valid).toBe(true)
  })

  it('logout с неверным CSRF → 403 CSRF_FAILED', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    setCsrfToken('csrf-wrong-placeholder')

    const logout = await postLogout(api)

    expect(logout.response.status).toBe(403)
    expect(logout.error?.error.code).toBe('CSRF_FAILED')
    expect(controller.isAuthenticated()).toBe(true)
  })

  it('logout без активной сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const logout = await postLogout(api)
    expect(logout.response.status).toBe(401)
    expect(logout.error?.error.code).toBe('UNAUTHENTICATED')
  })
})

describe('mock-fetch: app-config', () => {
  it('default-профиль N=100 из примера app-config-n100', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const expected = getExample<AppConfig>('config-app-config-n100')

    const result = await api.GET('/app-config')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(expected)
    expect(result.data?.search_result_limit).toBe(100)
    expect(result.data?.display_timezone).toBe('Europe/Moscow')
    expect(validateSchema('AppConfig', result.data).valid).toBe(true)
  })

  it('профиль N=10 отличается limit, timezone берётся из примера', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setConfigProfile('n10')
    const expected = getExample<AppConfig>('config-app-config-n10')

    const result = await api.GET('/app-config')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(expected)
    expect(result.data?.search_result_limit).toBe(10)
    expect(result.data?.search_result_limit).not.toBe(100)
    expect(result.data?.display_timezone).toBe(expected.display_timezone)
    expect(validateSchema('AppConfig', result.data).valid).toBe(true)
  })

  it('getAppConfig без сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const result = await api.GET('/app-config')
    expect(result.response.status).toBe(401)
    expect(result.error?.error.code).toBe('UNAUTHENTICATED')
  })
})

describe('mock-fetch: roots и companies', () => {
  it('listRoots normal → два корня из roots-two', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const expected = getExample<RootsResponse>('roots-two')

    const result = await api.GET('/roots')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(expected)
    expect(result.data?.items).toHaveLength(2)
    expect(validateSchema('RootsResponse', result.data).valid).toBe(true)
  })

  it('listRoots empty → пустой items из roots-empty', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setRootsEmpty(true)

    const result = await api.GET('/roots')

    expect(result.response.status).toBe(200)
    expect(result.data?.items).toEqual([])
    expect(validateSchema('RootsResponse', result.data).valid).toBe(true)
  })

  it('listCompanies normal → Atlas и Nova', async () => {
    const { api } = setup()
    await loginWorkerOne(api)
    const expected = getExample<CompaniesResponse>('companies-atlas-nova')

    const result = await api.GET('/companies')

    expect(result.response.status).toBe(200)
    expect(result.data).toEqual(expected)
    expect(result.data?.items.map((item) => item.name)).toEqual([
      'Atlas',
      'Nova',
    ])
    expect(validateSchema('CompaniesResponse', result.data).valid).toBe(true)
  })

  it('listCompanies empty → пустой items', async () => {
    const { api, controller } = setup()
    await loginWorkerOne(api)
    controller.setCompaniesEmpty(true)

    const result = await api.GET('/companies')

    expect(result.response.status).toBe(200)
    expect(result.data?.items).toEqual([])
    expect(validateSchema('CompaniesResponse', result.data).valid).toBe(true)
  })

  it('listRoots/listCompanies без сессии → 401 UNAUTHENTICATED', async () => {
    const { api } = setup()
    const roots = await api.GET('/roots')
    const companies = await api.GET('/companies')
    expect(roots.response.status).toBe(401)
    expect(companies.response.status).toBe(401)
  })
})

describe('mock-fetch: валидация запросов', () => {
  it('лишнее поле в login → 422 VALIDATION_ERROR без сессии', async () => {
    const { mockFetch, controller } = setup()
    const response = await mockFetch(
      request('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          login: 'worker.one',
          password: 'synthetic-placeholder-not-a-real-credential',
          extra: 'unknown',
        }),
      }),
    )

    expect(response.status).toBe(422)
    const body = await readError(response)
    expect(body.error.code).toBe('VALIDATION_ERROR')
    expect(body.error.field_errors.map((item) => item.field)).toContain('extra')
    expect(controller.isAuthenticated()).toBe(false)
    expect(validateSchema('ErrorResponse', body).valid).toBe(true)
  })

  it('отсутствует password → 422 с ошибкой поля password', async () => {
    const { mockFetch, controller } = setup()
    const response = await mockFetch(
      request('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login: 'worker.one' }),
      }),
    )

    expect(response.status).toBe(422)
    const body = await readError(response)
    expect(body.error.code).toBe('VALIDATION_ERROR')
    expect(body.error.field_errors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ field: 'password', code: 'REQUIRED' }),
      ]),
    )
    expect(controller.isAuthenticated()).toBe(false)
  })

  it('пустое/битое тело login → 422, не ложный успех', async () => {
    const { mockFetch, controller } = setup()
    const empty = await mockFetch(
      request('/auth/login', { method: 'POST', body: '' }),
    )
    const broken = await mockFetch(
      request('/auth/login', { method: 'POST', body: '{not-json' }),
    )

    expect(empty.status).toBe(422)
    expect(broken.status).toBe(422)
    expect(controller.isAuthenticated()).toBe(false)
  })
})

describe('mock-fetch: delay и reset', () => {
  it('управляемая задержка передаётся в инъектированный sleep', async () => {
    const { mockFetch, controller, sleeps } = setup()
    controller.setDelayMs(250)

    const response = await mockFetch(request('/health'))

    expect(response.status).toBe(200)
    expect(sleeps).toEqual([250])
  })

  it('нулевая задержка не вызывает sleep', async () => {
    const { mockFetch, sleeps } = setup()
    await mockFetch(request('/health'))
    expect(sleeps).toEqual([])
  })

  it('reset очищает session/delay/overrides', async () => {
    const { api, controller, mockFetch, sleeps } = setup()
    await loginWorkerOne(api)
    controller.setDelayMs(500)
    controller.setConfigProfile('n10')
    controller.setRootsEmpty(true)
    controller.setCompaniesEmpty(true)

    controller.reset()

    expect(controller.isAuthenticated()).toBe(false)
    expect(controller.getDelayMs()).toBe(0)
    expect(controller.getConfigProfile()).toBe('n100')
    expect(controller.isRootsEmpty()).toBe(false)
    expect(controller.isCompaniesEmpty()).toBe(false)

    const roots = await mockFetch(request('/roots'))
    expect(roots.status).toBe(401)
    expect(sleeps).toEqual([])
  })
})

describe('mock-fetch: отсутствие реальных секретов', () => {
  it('успешный login не возвращает и не эхо-тит пароль', async () => {
    const { api } = setup()
    const loginRequest = getExample<LoginRequest>('auth-login-request-worker-one')

    const result = await api.POST('/auth/login', { body: loginRequest })

    const serialized = JSON.stringify(result.data)
    expect(serialized).not.toContain(loginRequest.password)
    expect(result.data).not.toHaveProperty('password')
  })

  it('ошибка login не эхо-тит присланный пароль', async () => {
    const { api } = setup()
    const secret = 'secret-should-not-appear-anywhere'

    const result = await api.POST('/auth/login', {
      body: { login: 'worker.one', password: secret },
    })

    expect(result.response.status).toBe(401)
    expect(JSON.stringify(result.error)).not.toContain(secret)
  })
})
