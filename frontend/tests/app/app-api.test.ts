// LT-08.2: единая фабрика app-level API-клиента и переключатель real/mock.
//
// `createApiClient` подменяется шпионом, чтобы точно проверить аргументы
// выбора транспорта: mock-режим обязан получить `createMockFetch()`, а
// real-режим — только `{ mode: 'real' }` (без молчаливой подмены на mock).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as transport from '@/api/transport'
import { createAppApiClient, resolveAppApiMode } from '@/app/app-api'

vi.mock('@/api/transport', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/transport')>()
  return {
    ...actual,
    createApiClient: vi.fn(actual.createApiClient),
  }
})

const createApiClientMock = vi.mocked(transport.createApiClient)

beforeEach(() => {
  createApiClientMock.mockClear()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe('resolveAppApiMode — выбор режима по env', () => {
  it('возвращает mock только при точном значении', () => {
    expect(resolveAppApiMode('mock')).toBe('mock')
  })

  it('всё остальное, включая пустое значение, — real', () => {
    expect(resolveAppApiMode(undefined)).toBe('real')
    expect(resolveAppApiMode(null)).toBe('real')
    expect(resolveAppApiMode('')).toBe('real')
    expect(resolveAppApiMode('MOCK')).toBe('real')
    expect(resolveAppApiMode('real')).toBe('real')
    expect(resolveAppApiMode('anything-else')).toBe('real')
  })
})

describe('createAppApiClient — транспорт по режиму', () => {
  it('mock-режим получает mock-fetch', () => {
    createAppApiClient('mock')

    expect(createApiClientMock).toHaveBeenCalledTimes(1)
    const [options] = createApiClientMock.mock.calls[0]
    expect(options.mode).toBe('mock')
    expect(typeof options.fetch).toBe('function')
  })

  it('real-режим не подменяется mock-ом', () => {
    createAppApiClient('real')

    expect(createApiClientMock).toHaveBeenCalledTimes(1)
    expect(createApiClientMock.mock.calls[0][0]).toEqual({ mode: 'real' })
  })

  it('по умолчанию (VITE_API_MODE не задан) — real', () => {
    createAppApiClient()

    expect(createApiClientMock).toHaveBeenCalledWith({ mode: 'real' })
  })

  it('VITE_API_MODE=mock переключает на mock', () => {
    vi.stubEnv('VITE_API_MODE', 'mock')

    createAppApiClient()

    const [options] = createApiClientMock.mock.calls[0]
    expect(options.mode).toBe('mock')
    expect(typeof options.fetch).toBe('function')
  })
})
