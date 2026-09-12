// LT-08.1: общий in-memory реестр сброса приватного состояния.
//
// Проверяются регистрация, вызов ровно один раз за `resetPrivateState()`,
// изоляция от сбойного сброса, отсутствие вызова снятой подписки и отсутствие
// сетевых запросов.

import { afterEach, describe, expect, it, vi } from 'vitest'

import { registerPrivateStateReset, resetPrivateState } from '@/app/index'

describe('реестр сброса приватного состояния', () => {
  const unsubscribers: Array<() => void> = []

  function register(reset: () => void): () => void {
    const unsubscribe = registerPrivateStateReset(reset)
    unsubscribers.push(unsubscribe)
    return unsubscribe
  }

  afterEach(() => {
    while (unsubscribers.length > 0) {
      unsubscribers.pop()?.()
    }
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('вызывает каждый зарегистрированный сброс ровно один раз', () => {
    const first = vi.fn()
    const second = vi.fn()
    register(first)
    register(second)

    resetPrivateState()

    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
  })

  it('повторный вызов снова вызывает зарегистрированные сбросы', () => {
    const reset = vi.fn()
    register(reset)

    resetPrivateState()
    resetPrivateState()

    expect(reset).toHaveBeenCalledTimes(2)
  })

  it('сбойный сброс не мешает остальным', () => {
    const throwing = vi.fn((): void => {
      throw new Error('сбой сброса')
    })
    const healthy = vi.fn()
    register(throwing)
    register(healthy)

    expect(() => resetPrivateState()).not.toThrow()

    expect(throwing).toHaveBeenCalledTimes(1)
    expect(healthy).toHaveBeenCalledTimes(1)
  })

  it('снятая подписка не вызывается', () => {
    const active = vi.fn()
    const removed = vi.fn()
    register(active)
    const unsubscribe = register(removed)

    unsubscribe()
    resetPrivateState()

    expect(active).toHaveBeenCalledTimes(1)
    expect(removed).not.toHaveBeenCalled()
  })

  it('сброс, снятый во время вызова, не запускается', () => {
    const second = vi.fn()
    let unsubscribeSecond: () => void = () => undefined
    const first = vi.fn(() => {
      unsubscribeSecond()
    })
    register(first)
    unsubscribeSecond = register(second)

    resetPrivateState()

    expect(first).toHaveBeenCalledTimes(1)
    expect(second).not.toHaveBeenCalled()
  })

  it('не выполняет сетевых запросов', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    register(vi.fn())

    resetPrivateState()

    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
