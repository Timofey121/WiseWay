// LT-09.2: истечение сессии/блокировка (`401 UNAUTHENTICATED`) и сброс
// приватного состояния.
//
// Проверяются: `401 UNAUTHENTICATED` из любого API-вызова очищает
// CSRF/idempotency/polls и всё зарегистрированное приватное состояние,
// переводит сессию в `anonymous` и показывает вход реактивно; UI не отменяет
// серверную партию и не подменяет автора (никаких cancel/actor-запросов);
// повторный `clearSession()` не дублируется — очистку выполняет транспорт.

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getCsrfToken, resetSessionContext } from '@/api/session-context'
import { defaultIdempotencyStore } from '@/api/idempotency'
import { defaultPollRegistry } from '@/api/retry'
import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import {
  getAuthenticatedSession,
  getSessionStatus,
  resetSessionState,
} from '@/app/session-state'
import { registerPrivateStateReset } from '@/app/private-state-registry'
import { AuthGate } from '@/features/auth/auth-gate'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import type { Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'
const POLL_KEY = 'poll-batch-reset'

interface RecordingMock {
  readonly client: WiseWayApiClient
  readonly paths: string[]
}

function createRecordingClient(controller: MockController): RecordingMock {
  const mockFetch = createMockFetch(controller)
  const paths: string[] = []
  const fetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    paths.push(new URL(request.url, 'http://localhost').pathname)
    return mockFetch(input, init)
  }
  const client = createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch,
    retry: { maxAttempts: 1 },
  })
  return { client, paths }
}

let unregisterProbe: (() => void) | null = null

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
})

afterEach(() => {
  unregisterProbe?.()
  unregisterProbe = null
  vi.restoreAllMocks()
})

describe('401 UNAUTHENTICATED — сброс приватного состояния', () => {
  it('очищает сессию, приватное состояние и показывает вход без перезагрузки', async () => {
    const controller = new MockController()
    const session = getExample<Session>('auth-session-worker-one')
    controller.setSession(session)
    const { client, paths } = createRecordingClient(controller)

    render(<AuthGate client={client} />)
    await screen.findByRole('heading', { level: 1, name: 'WiseWay' })
    expect(getSessionStatus()).toBe('authenticated')
    expect(getCsrfToken()).toBe(session.csrf_token)

    // Приватное состояние предыдущей сессии.
    defaultIdempotencyStore.begin('createSortingBatch', { items: [] }, '')
    void defaultPollRegistry.run(POLL_KEY, () => new Promise(() => undefined))
    let probe: string | null = 'selection'
    unregisterProbe = registerPrivateStateReset(() => {
      probe = null
    })

    // Сессия истекает/блокируется: любой защищённый вызов даёт 401
    // UNAUTHENTICATED.
    controller.clearSession()
    await client.GET('/app-config')

    await screen.findByRole('heading', { name: 'Вход в WiseWay' })
    expect(getSessionStatus()).toBe('anonymous')
    expect(getAuthenticatedSession()).toBeNull()
    expect(getCsrfToken()).toBeNull()
    expect(probe).toBeNull()
    expect(defaultIdempotencyStore.retain('createSortingBatch', '')).toBeUndefined()
    expect(defaultPollRegistry.has(POLL_KEY)).toBe(false)
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument()
    // Ни отмены партии, ни смены автора: только проверка конфигурации.
    expect(paths.some((path) => /batch|cancel|actor/i.test(path))).toBe(false)
  })
})
