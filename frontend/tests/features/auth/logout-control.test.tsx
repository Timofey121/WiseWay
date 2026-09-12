// LT-09.2: доступное управление выходом и реактивный переход на экран входа.
//
// Проверяются: кнопка «Выйти» видна при аутентификации; успешный `204` очищает
// CSRF/idempotency/polls, сбрасывает приватное состояние и показывает вход без
// перезагрузки; неизвестный исход (сеть) сохраняет сессию и предлагает явный
// повтор; `403` не повторяется автоматически; запрос logout — с пустым телом,
// CSRF и без `Idempotency-Key`, без отмены партий и подмены автора.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getCsrfToken,
  resetSessionContext,
} from '@/api/session-context'
import { defaultIdempotencyStore } from '@/api/idempotency'
import { defaultPollRegistry } from '@/api/retry'
import { createApiClient } from '@/api/transport'
import {
  getAuthenticatedSession,
  getSessionStatus,
  resetSessionState,
} from '@/app/session-state'
import { registerPrivateStateReset } from '@/app/private-state-registry'
import { AuthGate } from '@/features/auth/auth-gate'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import { csrfFailedResponse } from '@/mocks/responses'
import type { Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'
const POLL_KEY = 'poll-batch-test'

interface RecordedRequest {
  readonly method: string
  readonly path: string
  readonly csrf: string | null
  readonly idempotencyKey: string | null
  body: string
}

function createMockClient(fetchImpl: MockFetch) {
  return createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch: fetchImpl,
    retry: { maxAttempts: 1 },
  })
}

/** Обёртка mock-fetch с записью запросов и программируемым исходом logout. */
function createRecordingFetch(controller: MockController): {
  fetch: MockFetch
  requests: RecordedRequest[]
  failLogoutNetwork: () => void
  failLogoutForbidden: () => void
  restoreLogout: () => void
} {
  const mockFetch = createMockFetch(controller)
  const requests: RecordedRequest[] = []
  let logoutBehavior: 'pass' | 'network' | 'forbidden' = 'pass'

  const fetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url, 'http://localhost')
    const recorded: RecordedRequest = {
      method: request.method,
      path: url.pathname,
      csrf: request.headers.get('X-CSRF-Token'),
      idempotencyKey: request.headers.get('Idempotency-Key'),
      body: '',
    }
    requests.push(recorded)

    if (url.pathname.endsWith('/auth/logout')) {
      if (logoutBehavior === 'network') {
        return Promise.reject(new TypeError('network down'))
      }
      if (logoutBehavior === 'forbidden') {
        return Promise.resolve(csrfFailedResponse('request-logout-403'))
      }
    }

    return (async () => {
      recorded.body = await request.clone().text()
      return mockFetch(input, init)
    })()
  }

  return {
    fetch,
    requests,
    failLogoutNetwork: () => {
      logoutBehavior = 'network'
    },
    failLogoutForbidden: () => {
      logoutBehavior = 'forbidden'
    },
    restoreLogout: () => {
      logoutBehavior = 'pass'
    },
  }
}

function createAuthenticatedController(): MockController {
  const controller = new MockController()
  controller.setSession(getExample<Session>('auth-session-worker-one'))
  return controller
}

async function renderAuthenticatedShell(controller: MockController) {
  const recording = createRecordingFetch(controller)
  const user = userEvent.setup()
  render(<AuthGate client={createMockClient(recording.fetch)} />)
  await screen.findByRole('heading', { level: 1, name: 'WiseWay' })
  return { user, recording }
}

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
})

afterEach(() => {
  resetPrivateStateProbe?.()
  resetPrivateStateProbe = null
  vi.restoreAllMocks()
})

let resetPrivateStateProbe: (() => void) | null = null

describe('LogoutControl — доступность', () => {
  it('показывает русскую кнопку «Выйти» при аутентификации', async () => {
    await renderAuthenticatedShell(createAuthenticatedController())

    expect(screen.getByRole('button', { name: 'Выйти' })).toBeVisible()
  })
})

describe('LogoutControl — успешный выход', () => {
  it('204 очищает сессию и приватное состояние и показывает вход без перезагрузки', async () => {
    const controller = createAuthenticatedController()
    const { user, recording } = await renderAuthenticatedShell(controller)
    const session = getExample<Session>('auth-session-worker-one')

    // Приватное состояние предыдущей сессии: idempotency, poll и probe.
    defaultIdempotencyStore.begin('createSortingBatch', { items: [] }, '')
    void defaultPollRegistry.run(POLL_KEY, () => new Promise(() => undefined))
    let probe: string | null = 'draft'
    resetPrivateStateProbe = registerPrivateStateReset(() => {
      probe = null
    })
    const hrefBefore = window.location.href

    await user.click(screen.getByRole('button', { name: 'Выйти' }))

    await screen.findByRole('heading', { name: 'Вход в WiseWay' })
    expect(getSessionStatus()).toBe('anonymous')
    expect(getAuthenticatedSession()).toBeNull()
    expect(getCsrfToken()).toBeNull()
    expect(defaultIdempotencyStore.retain('createSortingBatch', '')).toBeUndefined()
    expect(defaultPollRegistry.has(POLL_KEY)).toBe(false)
    expect(probe).toBeNull()
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument()
    expect(window.location.href).toBe(hrefBefore)

    // Ровно один logout: пустое тело, CSRF текущей сессии, без Idempotency-Key,
    // без отмены партий и подмены автора.
    const logoutRequests = recording.requests.filter((request) =>
      request.path.endsWith('/auth/logout'),
    )
    expect(logoutRequests).toHaveLength(1)
    expect(logoutRequests[0].method).toBe('POST')
    expect(logoutRequests[0].body).toBe('')
    expect(logoutRequests[0].csrf).toBe(session.csrf_token)
    expect(logoutRequests[0].idempotencyKey).toBeNull()
    expect(
      recording.requests.some((request) =>
        /batch|cancel|actor/i.test(request.path),
      ),
    ).toBe(false)
  })
})

describe('LogoutControl — неизвестный исход', () => {
  it('сетевой сбой сохраняет сессию и предлагает явный повтор, затем выход', async () => {
    const controller = createAuthenticatedController()
    const { user, recording } = await renderAuthenticatedShell(controller)
    recording.failLogoutNetwork()

    await user.click(screen.getByRole('button', { name: 'Выйти' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('сессия всё ещё активна')
    expect(
      screen.getByRole('button', { name: 'Повторить выход' }),
    ).toBeVisible()
    // Сессия НЕ очищена: ложный успех не заявлен.
    expect(getSessionStatus()).toBe('authenticated')
    expect(getCsrfToken()).not.toBeNull()
    expect(
      screen.getByRole('navigation', { name: 'Разделы приложения' }),
    ).toBeVisible()
    // Одна попытка logout + одна сверка session, без автоматического повтора.
    expect(
      recording.requests.filter((request) => request.path.endsWith('/auth/logout')),
    ).toHaveLength(1)

    recording.restoreLogout()
    await user.click(screen.getByRole('button', { name: 'Повторить выход' }))

    await screen.findByRole('heading', { name: 'Вход в WiseWay' })
    expect(getSessionStatus()).toBe('anonymous')
  })

  it('403 CSRF_FAILED не повторяется автоматически и сохраняет сессию', async () => {
    const controller = createAuthenticatedController()
    const { user, recording } = await renderAuthenticatedShell(controller)
    recording.failLogoutForbidden()

    await user.click(screen.getByRole('button', { name: 'Выйти' }))

    await screen.findByRole('alert')
    expect(
      recording.requests.filter((request) => request.path.endsWith('/auth/logout')),
    ).toHaveLength(1)
    expect(getSessionStatus()).toBe('authenticated')
    expect(
      screen.getByRole('button', { name: 'Повторить выход' }),
    ).toBeVisible()
  })
})

describe('LogoutControl — отсутствие персистирования', () => {
  it('не пишет URL/history/storage/cookie при выходе', async () => {
    const controller = createAuthenticatedController()
    const { user } = await renderAuthenticatedShell(controller)
    const setItemSpy = vi.spyOn(window.Storage.prototype, 'setItem')
    const pushStateSpy = vi.spyOn(window.history, 'pushState')
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
    const initialHref = window.location.href

    await user.click(screen.getByRole('button', { name: 'Выйти' }))
    await screen.findByRole('heading', { name: 'Вход в WiseWay' })

    expect(window.location.href).toBe(initialHref)
    expect(setItemSpy).not.toHaveBeenCalled()
    expect(pushStateSpy).not.toHaveBeenCalled()
    expect(replaceStateSpy).not.toHaveBeenCalled()
  })
})
