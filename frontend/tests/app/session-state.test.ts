// LT-08.2: in-memory контейнер присутствия сессии приложения.
//
// Проверяются состояние по умолчанию, переходы, уведомление подписчиков,
// сброс через общий реестр LT-08.1, отсутствие хранения токена и отсутствие
// сетевых запросов.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { resetPrivateState } from '@/app/index'
import {
  getAuthenticatedActor,
  getAuthenticatedSession,
  getSessionStatus,
  markAnonymous,
  markAuthenticated,
  resetSessionState,
  subscribeSessionStatus,
  type AuthenticatedSession,
} from '@/app/session-state'

const SESSION: AuthenticatedSession = {
  actor: {
    user_id: 'user-demo-worker-1',
    login: 'worker.one',
    display_name: 'Иван Рабочий',
    role: 'WORKER',
  },
  expires_at: '2031-05-10T17:30:00Z',
}

const SESSION_TWO: AuthenticatedSession = {
  actor: {
    user_id: 'user-demo-admin-1',
    login: 'admin.one',
    display_name: 'Администратор Демо',
    role: 'ADMIN',
  },
  expires_at: '2031-05-10T17:30:00Z',
}

beforeEach(() => {
  resetSessionState()
})

describe('session-state — состояние и переходы', () => {
  it('по умолчанию находится в anonymous', () => {
    expect(getSessionStatus()).toBe('anonymous')
  })

  it('markAuthenticated переводит в authenticated', () => {
    markAuthenticated()
    expect(getSessionStatus()).toBe('authenticated')
  })

  it('markAnonymous возвращает в anonymous', () => {
    markAuthenticated()
    markAnonymous()
    expect(getSessionStatus()).toBe('anonymous')
  })

  it('уведомляет подписчика об изменении и отписывает его', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSessionStatus(listener)

    markAuthenticated()
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
    markAnonymous()
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('не уведомляет при повторной установке того же состояния', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSessionStatus(listener)

    markAnonymous() // уже anonymous
    expect(listener).not.toHaveBeenCalled()

    markAuthenticated()
    markAuthenticated()
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
  })
})

describe('session-state — сброс приватного состояния', () => {
  it('resetPrivateState возвращает контейнер в anonymous', () => {
    markAuthenticated()

    resetPrivateState()

    expect(getSessionStatus()).toBe('anonymous')
  })

  it('resetSessionState сбрасывает состояние', () => {
    markAuthenticated()
    resetSessionState()
    expect(getSessionStatus()).toBe('anonymous')
  })
})

describe('session-state — безопасность', () => {
  it('не хранит токен и не выполняет сетевых запросов', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    markAuthenticated()
    markAnonymous()
    resetPrivateState()

    expect(fetchSpy).not.toHaveBeenCalled()
    // В публичном API контейнера нет ни токена, ни CSRF: они остаются в
    // `@/api/session-context`.
    const sessionState = await import('@/app/session-state')
    const tokenLike = Object.keys(sessionState).filter((name) =>
      /token|csrf|password/i.test(name),
    )
    expect(tokenLike).toEqual([])

    vi.unstubAllGlobals()
  })
})

describe('session-state — серверная сессия в памяти (LT-09.1)', () => {
  it('по умолчанию не содержит сессии', () => {
    expect(getAuthenticatedSession()).toBeNull()
    expect(getAuthenticatedActor()).toBeNull()
  })

  it('markAuthenticated сохраняет серверный actor и expires_at', () => {
    markAuthenticated(SESSION)

    expect(getSessionStatus()).toBe('authenticated')
    expect(getAuthenticatedSession()).toEqual(SESSION)
    expect(getAuthenticatedActor()).toEqual(SESSION.actor)
  })

  it('markAnonymous очищает сохранённую сессию', () => {
    markAuthenticated(SESSION)
    markAnonymous()

    expect(getSessionStatus()).toBe('anonymous')
    expect(getAuthenticatedSession()).toBeNull()
  })

  it('resetPrivateState очищает сохранённую сессию', () => {
    markAuthenticated(SESSION)

    resetPrivateState()

    expect(getAuthenticatedSession()).toBeNull()
    expect(getSessionStatus()).toBe('anonymous')
  })

  it('смена сессии при уже аутентифицированном статусе уведомляет подписчика', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSessionStatus(listener)
    markAuthenticated(SESSION)
    listener.mockClear()

    markAuthenticated(SESSION_TWO)

    expect(listener).toHaveBeenCalledTimes(1)
    expect(getAuthenticatedActor()).toEqual(SESSION_TWO.actor)
    unsubscribe()
  })

  it('не хранит csrf-токен и пароль в состоянии сессии', () => {
    markAuthenticated(SESSION)

    const stored = getAuthenticatedSession()
    expect(stored).not.toBeNull()
    const keys = Object.keys(stored as object)
    expect(keys).toEqual(['actor', 'expires_at'])
    expect(keys.some((key) => /csrf|token|password/i.test(key))).toBe(false)
    expect(JSON.stringify(stored)).not.toMatch(/csrf|password/i)
  })
})
