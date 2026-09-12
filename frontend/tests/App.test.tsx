// LT-09.1: композиция приложения через auth-гейт.
//
// Проверяются: bootstrap вызывает `GET /session` до защищённой оболочки; без
// сессии показывается экран входа, а не оболочка; до входа `GET /app-config`
// не запрашивается; активная серверная сессия показывает оболочку с именем и
// русской подписью роли.

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App'
import { resetSessionContext } from '../src/api/session-context'
import { TEST_FETCH_GLOBAL, resetPrivateState } from '../src/app/index'
import { resetSessionState } from '../src/app/session-state'
import { createMockFetch, MockController, type MockFetch } from '../src/mocks'
import { getExample } from '../src/mocks/data'
import type { Session } from '../src/mocks/types'

interface RecordingMock {
  readonly fetch: MockFetch
  readonly paths: string[]
}

/** Mock-fetch с учётом путей запросов приложения. */
function createRecordingMock(controller: MockController): RecordingMock {
  const mockFetch = createMockFetch(controller)
  const paths: string[] = []
  const fetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    paths.push(new URL(request.url, 'http://localhost').pathname)
    return mockFetch(input, init)
  }
  return { fetch, paths }
}

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
  // Приложение тестируется на контролируемом mock-транспорте.
  vi.stubEnv('VITE_API_MODE', 'mock')
})

afterEach(() => {
  resetPrivateState()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('App — auth-гейт на старте', () => {
  it('без сессии показывает экран входа, а не защищённую оболочку', async () => {
    const { fetch } = createRecordingMock(new MockController())
    vi.stubGlobal(TEST_FETCH_GLOBAL, fetch)

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Вход в WiseWay' }),
    ).toBeVisible()
    expect(screen.getByLabelText('Логин')).toBeVisible()
    expect(screen.getByLabelText('Пароль')).toBeVisible()
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument()
  })

  it('до входа запрашивает только сессию, но не app-config', async () => {
    const { fetch, paths } = createRecordingMock(new MockController())
    vi.stubGlobal(TEST_FETCH_GLOBAL, fetch)

    render(<App />)
    await screen.findByRole('heading', { name: 'Вход в WiseWay' })

    expect(paths).toEqual(['/api/v1/session'])
  })

  it('с активной серверной сессией показывает оболочку с именем и ролью', async () => {
    const controller = new MockController()
    const session = getExample<Session>('auth-session-admin')
    controller.setSession(session)
    const { fetch, paths } = createRecordingMock(controller)
    vi.stubGlobal(TEST_FETCH_GLOBAL, fetch)

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'WiseWay' }),
    ).toBeVisible()
    expect(
      screen.getByRole('navigation', { name: 'Разделы приложения' }),
    ).toBeVisible()
    // Стартовый раздел после входа — пустой «Поиск».
    expect(
      screen.getByRole('heading', { level: 2, name: 'Поиск' }),
    ).toBeVisible()
    // Имя и роль — из серверного ответа, роль показана по-русски.
    expect(screen.getByText(session.actor.display_name)).toBeVisible()
    expect(screen.getByText('Администратор')).toBeVisible()
    // Bootstrap-проверка предшествует конфигурации.
    expect(paths[0]).toBe('/api/v1/session')
    expect(paths).toContain('/api/v1/app-config')
  })
})
