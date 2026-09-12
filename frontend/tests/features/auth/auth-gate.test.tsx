// LT-09.1: auth-гейт — bootstrap-проверка сессии и выбор экрана.
//
// Проверяются: русская загрузка до ответа; вход при анонимной сессии; оболочка
// с именем/ролью при серверной сессии; экран недоступности при 5xx с повтором,
// который НЕ показывает форму входа и не выдаёт сбой за выход.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionContext, getCsrfToken } from '@/api/session-context'
import { createApiClient } from '@/api/transport'
import {
  getAuthenticatedSession,
  resetSessionState,
} from '@/app/session-state'
import { AuthGate } from '@/features/auth/auth-gate'
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
        'X-Request-ID': 'request-gate-500',
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

describe('AuthGate — bootstrap', () => {
  it('показывает русскую загрузку до ответа сервера', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const mockFetch = createMockFetch(new MockController())
    const gatedFetch: MockFetch = async (input, init) => {
      await gate
      return mockFetch(input, init)
    }
    render(<AuthGate client={createMockClient(gatedFetch)} />)

    expect(screen.getByRole('status')).toHaveTextContent('Проверка сессии')

    release()
    await screen.findByRole('heading', { name: 'Вход в WiseWay' })
  })

  it('без сессии показывает вход и не показывает оболочку', async () => {
    render(
      <AuthGate
        client={createMockClient(createMockFetch(new MockController()))}
      />,
    )

    expect(
      await screen.findByRole('heading', { name: 'Вход в WiseWay' }),
    ).toBeVisible()
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument()
  })

  it('с серверной сессией показывает оболочку с именем и русской ролью', async () => {
    const controller = new MockController()
    const session = getExample<Session>('auth-session-admin')
    controller.setSession(session)

    render(<AuthGate client={createMockClient(createMockFetch(controller))} />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'WiseWay' }),
    ).toBeVisible()
    expect(
      screen.getByRole('heading', { level: 2, name: 'Поиск' }),
    ).toBeVisible()
    expect(screen.getByText(session.actor.display_name)).toBeVisible()
    expect(screen.getByText('Администратор')).toBeVisible()
  })
})

describe('AuthGate — вход через форму', () => {
  it('успешный вход показывает оболочку и сохраняет серверную сессию и CSRF', async () => {
    const user = userEvent.setup()
    const controller = new MockController()
    render(<AuthGate client={createMockClient(createMockFetch(controller))} />)

    await screen.findByRole('heading', { name: 'Вход в WiseWay' })
    await user.type(screen.getByLabelText('Логин'), 'worker.one')
    await user.type(
      screen.getByLabelText('Пароль'),
      'synthetic-placeholder-not-a-real-credential',
    )
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'WiseWay' }),
      ).toBeVisible(),
    )
    const session = getExample<Session>('auth-session-worker-one')
    expect(getAuthenticatedSession()?.actor).toEqual(session.actor)
    expect(getCsrfToken()).toBe(session.csrf_token)
    expect(
      screen.getByRole('heading', { level: 2, name: 'Поиск' }),
    ).toBeVisible()
  })
})

describe('AuthGate — недоступность', () => {
  it('при 5xx показывает безопасное сообщение с повтором, а не вход', async () => {
    const failingFetch: MockFetch = () => Promise.resolve(internalErrorResponse())
    render(<AuthGate client={createMockClient(failingFetch)} />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Не удалось проверить сессию')
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeVisible()
  })

  it('повтор после сбоя приводит к экрану входа при отсутствии сессии', async () => {
    const user = userEvent.setup()
    const mockFetch = createMockFetch(new MockController())
    let failing = true
    const flakyFetch: MockFetch = (input, init) => {
      if (failing) {
        return Promise.resolve(internalErrorResponse())
      }
      return mockFetch(input, init)
    }
    render(<AuthGate client={createMockClient(flakyFetch)} />)

    await screen.findByRole('alert')
    failing = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Вход в WiseWay' }),
      ).toBeVisible(),
    )
  })
})
