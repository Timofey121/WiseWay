// LT-09.1: экран входа.
//
// Проверяются: доступность кнопки и русская причина; отправка ровно
// `{login, password}`; успех с серверной сессией и немедленным удалением пароля;
// общая ошибка `LOGIN_FAILED` без раскрытия поля и без изменения сессии;
// недоступность сети с повтором; отсутствие пароля в URL/history/storage/cookie
// и логах.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionContext } from '@/api/session-context'
import { createApiClient } from '@/api/transport'
import { getSessionStatus, resetSessionState } from '@/app/session-state'
import { LoginScreen } from '@/features/auth/login-screen'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import type { Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'
const PASSWORD = 'synthetic-placeholder-not-a-real-credential'
const LOGIN = 'worker.one'

interface CapturedClient {
  client: ReturnType<typeof createApiClient>
  bodies: string[]
}

/** Mock-клиент, сохраняющий тела POST /auth/login для точной проверки. */
function createCapturingClient(
  controller: MockController = new MockController(),
): CapturedClient {
  const mockFetch = createMockFetch(controller)
  const bodies: string[] = []
  const capturingFetch: MockFetch = async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const path = new URL(request.url, 'http://localhost').pathname
    if (request.method === 'POST' && path === '/api/v1/auth/login') {
      bodies.push(await request.clone().text())
    }
    return mockFetch(input, init)
  }
  const client = createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch: capturingFetch,
    retry: { maxAttempts: 1 },
  })
  return { client, bodies }
}

async function fillCredentials(
  user: ReturnType<typeof userEvent.setup>,
  login: string = LOGIN,
  password: string = PASSWORD,
): Promise<void> {
  await user.type(screen.getByLabelText('Логин'), login)
  await user.type(screen.getByLabelText('Пароль'), password)
}

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'cookie')
})

describe('LoginScreen — доступность кнопки входа', () => {
  it('недоступна с русской причиной, пока поля пусты, и включается после заполнения', async () => {
    const user = userEvent.setup()
    const { client } = createCapturingClient()
    render(<LoginScreen client={client} onAuthenticated={vi.fn()} />)

    const submit = screen.getByRole('button', { name: 'Войти' })
    expect(submit).toBeDisabled()
    expect(
      screen.getByText('Введите логин и пароль, чтобы войти.'),
    ).toBeVisible()

    await user.type(screen.getByLabelText('Логин'), LOGIN)
    expect(submit).toBeDisabled()
    expect(screen.getByText('Введите пароль, чтобы войти.')).toBeVisible()

    await user.type(screen.getByLabelText('Пароль'), PASSWORD)
    expect(submit).toBeEnabled()
    expect(
      screen.queryByText('Введите пароль, чтобы войти.'),
    ).not.toBeInTheDocument()
  })
})

describe('LoginScreen — успешный вход', () => {
  it('отправляет ровно {login, password}, отдаёт серверную сессию и очищает пароль', async () => {
    const user = userEvent.setup()
    const { client, bodies } = createCapturingClient()
    const onAuthenticated = vi.fn()
    render(<LoginScreen client={client} onAuthenticated={onAuthenticated} />)

    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledTimes(1)
    })
    const session = getExample<Session>('auth-session-worker-one')
    expect(onAuthenticated.mock.calls[0][0]).toEqual(session)
    expect(bodies).toHaveLength(1)
    expect(JSON.parse(bodies[0])).toEqual({
      login: LOGIN,
      password: PASSWORD,
    })
    expect(bodies[0]).not.toMatch(/actor_id/)
    // Пароль удалён из поля сразу после успеха.
    expect((screen.getByLabelText('Пароль') as HTMLInputElement).value).toBe('')
  })
})

describe('LoginScreen — неверные учётные данные', () => {
  it('показывает одно общее сообщение, сохраняет логин и не меняет сессию', async () => {
    const user = userEvent.setup()
    const { client } = createCapturingClient()
    const onAuthenticated = vi.fn()
    render(<LoginScreen client={client} onAuthenticated={onAuthenticated} />)

    await fillCredentials(user, LOGIN, 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Неверный логин или пароль.')
    // Не раскрываем, какое именно поле неверно.
    expect(alert.textContent).not.toMatch(/логин невер|пароль невер/i)
    expect(screen.getByLabelText('Логин')).toHaveValue(LOGIN)
    expect(onAuthenticated).not.toHaveBeenCalled()
    expect(getSessionStatus()).toBe('anonymous')
  })
})

describe('LoginScreen — недоступность сервиса', () => {
  it('показывает безопасное сообщение и повторяет отправку по кнопке', async () => {
    const user = userEvent.setup()
    const controller = new MockController()
    const mockFetch = createMockFetch(controller)
    let failing = true
    const flakyFetch: MockFetch = (input, init) => {
      if (failing) {
        return Promise.reject(new TypeError('network down'))
      }
      return mockFetch(input, init)
    }
    const client = createApiClient({
      mode: 'mock',
      baseUrl: BASE_URL,
      fetch: flakyFetch,
      retry: { maxAttempts: 1 },
    })
    const onAuthenticated = vi.fn()
    render(<LoginScreen client={client} onAuthenticated={onAuthenticated} />)

    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Не удалось связаться с сервером')
    expect(onAuthenticated).not.toHaveBeenCalled()

    failing = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))

    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledTimes(1)
    })
  })
})

describe('LoginScreen — отсутствие персистирования секретов', () => {
  it('не пишет пароль в URL/history/storage/cookie и не логирует его', async () => {
    const user = userEvent.setup()
    const { client, bodies } = createCapturingClient()
    const setItemSpy = vi.spyOn(window.Storage.prototype, 'setItem')
    const pushStateSpy = vi.spyOn(window.history, 'pushState')
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined)
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const errorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined)
    const cookieWrites: string[] = []
    const descriptor = Object.getOwnPropertyDescriptor(
      Object.getPrototypeOf(document) as object,
      'cookie',
    )
    Object.defineProperty(document, 'cookie', {
      configurable: true,
      get: () => descriptor?.get?.call(document) as string,
      set: (value: string) => {
        cookieWrites.push(value)
        descriptor?.set?.call(document, value)
      },
    })
    const initialHref = window.location.href
    const initialHistoryState = window.history.state

    render(<LoginScreen client={client} onAuthenticated={vi.fn()} />)
    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    await waitFor(() => expect(bodies).toHaveLength(1))

    expect(window.location.href).toBe(initialHref)
    expect(window.history.state).toBe(initialHistoryState)
    expect(pushStateSpy).not.toHaveBeenCalled()
    expect(replaceStateSpy).not.toHaveBeenCalled()
    expect(setItemSpy).not.toHaveBeenCalled()
    expect(cookieWrites).toEqual([])
    const logCalls = [
      ...logSpy.mock.calls,
      ...infoSpy.mock.calls,
      ...warnSpy.mock.calls,
      ...errorSpy.mock.calls,
    ]
    expect(JSON.stringify(logCalls)).not.toContain(PASSWORD)
  })
})
