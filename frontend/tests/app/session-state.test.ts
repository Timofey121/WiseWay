// LT-08.2: in-memory контейнер присутствия сессии приложения.
//
// Проверяются состояние по умолчанию, переходы, уведомление подписчиков,
// сброс через общий реестр LT-08.1, отсутствие хранения токена и отсутствие
// сетевых запросов.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { resetPrivateState } from '@/app/index'
import {
  getSessionStatus,
  markAnonymous,
  markAuthenticated,
  resetSessionState,
  subscribeSessionStatus,
} from '@/app/session-state'

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
