// LT-09.2: логика выхода и сверки неизвестного исхода.
//
// Проверяются: `POST /auth/logout` с пустым телом, CSRF через транспорт и без
// `Idempotency-Key`; `204` — подтверждённый выход; `401 UNAUTHENTICATED` —
// сессия уже недействительна; сетевой сбой/`5xx` не выдаётся за успех и
// разрешается повторным чтением `GET /session`; `403` не повторяется
// автоматически. Никакого выдуманного session backend и повторных logout нет.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionContext, setCsrfToken } from '@/api/session-context'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import { performLogout } from '@/features/auth/logout'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import {
  csrfFailedResponse,
  unauthenticatedResponse,
} from '@/mocks/responses'
import type { Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'

interface RecordedRequest {
  readonly method: string
  readonly path: string
  readonly csrf: string | null
  readonly idempotencyKey: string | null
  body: string
}

function createClient(fetchImpl: MockFetch): WiseWayApiClient {
  return createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch: fetchImpl,
    retry: { maxAttempts: 1 },
  })
}

function createAuthenticatedController(): {
  controller: MockController
  session: Session
} {
  const controller = new MockController()
  const session = getExample<Session>('auth-session-worker-one')
  controller.setSession(session)
  return { controller, session }
}

/** Обёртка mock-fetch с записью запросов и программируемым сбоем logout. */
function createRecordingFetch(
  controller: MockController,
  onLogout: 'pass' | 'network' | 'unauthorized' | 'forbidden',
): { fetch: MockFetch; requests: RecordedRequest[] } {
  const mockFetch = createMockFetch(controller)
  const requests: RecordedRequest[] = []

  const fetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url, 'http://localhost')
    requests.push({
      method: request.method,
      path: url.pathname,
      csrf: request.headers.get('X-CSRF-Token'),
      idempotencyKey: request.headers.get('Idempotency-Key'),
      body: '',
    })
    const recorded = requests[requests.length - 1]

    if (url.pathname.endsWith('/auth/logout') && onLogout !== 'pass') {
      if (onLogout === 'network') {
        return Promise.reject(new TypeError('network down'))
      }
      if (onLogout === 'unauthorized') {
        return Promise.resolve(unauthenticatedResponse('request-logout-401'))
      }
      return Promise.resolve(csrfFailedResponse('request-logout-403'))
    }

    return (async () => {
      recorded.body = await request.clone().text()
      return mockFetch(input, init)
    })()
  }

  return { fetch, requests }
}

beforeEach(() => {
  resetSessionContext()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('performLogout — подтверждённый выход', () => {
  it('204: одна попытка, пустое тело, CSRF из сессии, без Idempotency-Key', async () => {
    const { controller, session } = createAuthenticatedController()
    setCsrfToken(session.csrf_token)
    const { fetch, requests } = createRecordingFetch(controller, 'pass')

    const result = await performLogout(createClient(fetch))

    expect(result.status).toBe('logged_out')
    expect(requests).toHaveLength(1)
    const logout = requests[0]
    expect(logout.method).toBe('POST')
    expect(logout.path).toBe('/api/v1/auth/logout')
    expect(logout.body).toBe('')
    expect(logout.csrf).toBe(session.csrf_token)
    expect(logout.idempotencyKey).toBeNull()
    // Серверная сессия mock завершена; клиентский сброс выполняет auth-lifecycle.
    expect(controller.isAuthenticated()).toBe(false)
  })

  it('401 UNAUTHENTICATED на logout: сессия уже недействительна', async () => {
    const { controller } = createAuthenticatedController()
    const { fetch, requests } = createRecordingFetch(controller, 'unauthorized')

    const result = await performLogout(createClient(fetch))

    expect(result.status).toBe('logged_out')
    // Без сверки: 401 на самом logout уже подтверждает отсутствие сессии.
    expect(requests).toHaveLength(1)
    expect(requests[0].path).toBe('/api/v1/auth/logout')
  })
})

describe('performLogout — неизвестный исход сверяется с GET /session', () => {
  it('сетевой сбой logout и активная сессия: still_authenticated, без повтора', async () => {
    const { controller } = createAuthenticatedController()
    const { fetch, requests } = createRecordingFetch(controller, 'network')

    const result = await performLogout(createClient(fetch))

    expect(result.status).toBe('still_authenticated')
    expect(result.error?.code).toBe('NETWORK_ERROR')
    expect(controller.isAuthenticated()).toBe(true)
    expect(requests.map((request) => request.path)).toEqual([
      '/api/v1/auth/logout',
      '/api/v1/session',
    ])
  })

  it('сетевой сбой logout и 401 на /session: logged_out', async () => {
    const { controller } = createAuthenticatedController()
    const { fetch } = createRecordingFetch(controller, 'network')
    const baseFetch = fetch
    const logoutThenGone: MockFetch = (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init)
      const url = new URL(request.url, 'http://localhost')
      if (url.pathname.endsWith('/session')) {
        controller.clearSession()
        return Promise.resolve(unauthenticatedResponse('request-session-401'))
      }
      return baseFetch(input, init)
    }

    const result = await performLogout(createClient(logoutThenGone))

    expect(result.status).toBe('logged_out')
  })

  it('сбой logout и сбой /session: unknown, успех не заявляется', async () => {
    const { controller } = createAuthenticatedController()
    const baseFetch = createMockFetch(controller)
    const bothNetworkDown: MockFetch = (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init)
      const url = new URL(request.url, 'http://localhost')
      if (
        url.pathname.endsWith('/auth/logout') ||
        url.pathname.endsWith('/session')
      ) {
        return Promise.reject(new TypeError('network down'))
      }
      return baseFetch(input, init)
    }

    const result = await performLogout(createClient(bothNetworkDown))

    expect(result.status).toBe('unknown')
    expect(controller.isAuthenticated()).toBe(true)
  })
})

describe('performLogout — 403 не повторяется', () => {
  it('CSRF_FAILED: одна попытка logout, сессия активна, явный повтор', async () => {
    const { controller } = createAuthenticatedController()
    const { fetch, requests } = createRecordingFetch(controller, 'forbidden')

    const result = await performLogout(createClient(fetch))

    expect(result.status).toBe('still_authenticated')
    expect(result.error?.status).toBe(403)
    expect(result.error?.code).toBe('CSRF_FAILED')
    const logoutAttempts = requests.filter((request) =>
      request.path.endsWith('/auth/logout'),
    )
    expect(logoutAttempts).toHaveLength(1)
    expect(controller.isAuthenticated()).toBe(true)
  })
})
