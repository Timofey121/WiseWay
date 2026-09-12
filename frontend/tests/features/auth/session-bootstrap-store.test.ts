// LT-09.1: in-memory store bootstrap-проверки сессии.
//
// Проверяются состояния `checking`/`anonymous`/`authenticated`/`unavailable`,
// различение `401 UNAUTHENTICATED` и сетевого/5xx сбоя, фиксация серверного
// actor/`expires_at` и CSRF-токена, повтор и отбрасывание поздних ответов.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getCsrfToken,
  resetSessionContext,
} from '@/api/session-context'
import { createApiClient } from '@/api/transport'
import {
  getAuthenticatedSession,
  getSessionStatus,
  resetSessionState,
} from '@/app/session-state'
import { createSessionBootstrapStore } from '@/features/auth/session-bootstrap-store'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import type { ErrorResponse, Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'

function createMockClient(fetchImpl: MockFetch) {
  return createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch: fetchImpl,
    retry: { maxAttempts: 1 },
  })
}

function internalErrorResponse(): Response {
  return new Response(
    JSON.stringify(getExample<ErrorResponse>('error-internal-error')),
    {
      status: 500,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': 'request-bootstrap-500',
      },
    },
  )
}

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('session-bootstrap-store — состояния', () => {
  it('до start находится в checking', () => {
    const store = createSessionBootstrapStore(
      createMockClient(createMockFetch(new MockController())),
    )
    expect(store.getSnapshot().status).toBe('checking')
  })

  it('без mock-сессии получает 401 UNAUTHENTICATED и становится anonymous', async () => {
    const store = createSessionBootstrapStore(
      createMockClient(createMockFetch(new MockController())),
    )

    store.start()

    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('anonymous')
    })
    expect(getSessionStatus()).toBe('anonymous')
    expect(getAuthenticatedSession()).toBeNull()
    expect(getCsrfToken()).toBeNull()
  })

  it('с активной сессией фиксирует actor/expires_at и CSRF-токен', async () => {
    const controller = new MockController()
    const session = getExample<Session>('auth-session-worker-one')
    controller.setSession(session)
    const store = createSessionBootstrapStore(
      createMockClient(createMockFetch(controller)),
    )

    store.start()

    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('authenticated')
    })
    expect(getSessionStatus()).toBe('authenticated')
    expect(getAuthenticatedSession()).toEqual({
      actor: session.actor,
      expires_at: session.expires_at,
    })
    expect(getCsrfToken()).toBe(session.csrf_token)
  })

  it('сетевой сбой даёт unavailable и не считается анонимностью', async () => {
    const failingFetch: MockFetch = () => Promise.reject(new TypeError('fail'))
    const store = createSessionBootstrapStore(createMockClient(failingFetch))

    store.start()

    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('unavailable')
    })
    expect(store.getSnapshot().error?.code).toBe('NETWORK_ERROR')
    expect(getSessionStatus()).toBe('anonymous')
  })

  it('5xx даёт unavailable с безопасным кодом и сообщением', async () => {
    const failingFetch: MockFetch = () => Promise.resolve(internalErrorResponse())
    const store = createSessionBootstrapStore(createMockClient(failingFetch))

    store.start()

    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('unavailable')
    })
    expect(store.getSnapshot().error?.code).toBe('INTERNAL_ERROR')
    expect(store.getSnapshot().error?.message).toMatch(/[А-Яа-я]/)
    expect(getSessionStatus()).toBe('anonymous')
  })
})

describe('session-bootstrap-store — повтор и вход', () => {
  it('retry после сбоя успешно проверяет сессию', async () => {
    const controller = new MockController()
    const session = getExample<Session>('auth-session-worker-two')
    const mockFetch = createMockFetch(controller)
    let failing = true
    const flakyFetch: MockFetch = (input, init) => {
      if (failing) {
        return Promise.resolve(internalErrorResponse())
      }
      return mockFetch(input, init)
    }
    const store = createSessionBootstrapStore(createMockClient(flakyFetch))

    store.start()
    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('unavailable')
    })

    failing = false
    controller.setSession(session)
    store.retry()

    await vi.waitFor(() => {
      expect(store.getSnapshot().status).toBe('authenticated')
    })
    expect(getAuthenticatedSession()?.actor.login).toBe(session.actor.login)
  })

  it('completeLogin фиксирует серверную сессию и CSRF', async () => {
    const store = createSessionBootstrapStore(
      createMockClient(createMockFetch(new MockController())),
    )
    const session = getExample<Session>('auth-session-admin')

    store.completeLogin(session)

    expect(store.getSnapshot().status).toBe('authenticated')
    expect(getAuthenticatedSession()).toEqual({
      actor: session.actor,
      expires_at: session.expires_at,
    })
    expect(getCsrfToken()).toBe(session.csrf_token)
  })
})
