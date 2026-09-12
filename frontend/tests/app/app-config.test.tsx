// LT-08.2: провайдер загрузки app-config.
//
// Проверяются гейтирование по сессии (анонимно — ноль запросов), загрузка
// n100/n10 из ответа mock-транспорта без хардкода значений, честное состояние
// загрузки, ошибка без выдуманных значений по умолчанию и явный повтор, а
// также очистка конфигурации при сбросе приватного состояния.

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionContext } from '@/api/session-context'
import { createApiClient } from '@/api/transport'
import {
  AppConfigProvider,
  useAppConfig,
} from '@/app/index'
import { resetPrivateState } from '@/app/index'
import { markAuthenticated, resetSessionState } from '@/app/session-state'
import { createMockFetch, MockController, type MockFetch } from '@/mocks'
import { getExample } from '@/mocks/data'
import type { ErrorResponse, Session } from '@/mocks/types'

const BASE_URL = 'http://localhost/api/v1'
const SESSION_EXAMPLE_ID = 'auth-session-worker-one'

function createController(profile: 'n100' | 'n10'): MockController {
  const controller = new MockController()
  controller.setConfigProfile(profile)
  controller.setSession(getExample<Session>(SESSION_EXAMPLE_ID))
  return controller
}

interface CountedClient {
  client: ReturnType<typeof createApiClient>
  calls: string[]
}

/** Mock-клиент с активной сессией и учётом путей запросов. */
function createCountedMockClient(profile: 'n100' | 'n10' = 'n100'): CountedClient {
  const controller = createController(profile)
  const mockFetch = createMockFetch(controller)
  const calls: string[] = []
  const countedFetch: MockFetch = (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    calls.push(new URL(request.url, 'http://localhost').pathname)
    return mockFetch(input, init)
  }
  const client = createApiClient({
    mode: 'mock',
    baseUrl: BASE_URL,
    fetch: countedFetch,
  })
  return { client, calls }
}

function ConfigProbe() {
  const { status, config, error, reload } = useAppConfig()
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="limit">
        {config ? String(config.search_result_limit) : 'none'}
      </span>
      <span data-testid="timezone">
        {config ? config.display_timezone : 'none'}
      </span>
      <span data-testid="error-code">{error ? error.code : 'none'}</span>
      <button type="button" onClick={reload}>
        Перезагрузить настройки
      </button>
    </div>
  )
}

function renderProvider(client: ReturnType<typeof createApiClient>) {
  return render(
    <AppConfigProvider client={client}>
      <ConfigProbe />
    </AppConfigProvider>,
  )
}

beforeEach(() => {
  resetSessionState()
  resetSessionContext()
})

afterEach(() => {
  resetPrivateState()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AppConfigProvider — гейтирование по сессии', () => {
  it('в анонимном состоянии остаётся idle и не делает запросов', async () => {
    const { client, calls } = createCountedMockClient()

    renderProvider(client)

    expect(screen.getByTestId('status')).toHaveTextContent('idle')
    await act(async () => {
      await Promise.resolve()
    })
    expect(calls).toEqual([])
    expect(screen.getByTestId('status')).toHaveTextContent('idle')
  })

  it('запрашивает конфигурацию только после отметки об аутентификации', async () => {
    const { client, calls } = createCountedMockClient()

    renderProvider(client)
    expect(calls).toEqual([])

    await act(async () => {
      markAuthenticated()
    })

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
    expect(calls).toEqual(['/api/v1/app-config'])
  })
})

describe('AppConfigProvider — загрузка конфигурации', () => {
  it('показывает русское состояние загрузки до ответа', async () => {
    const controller = createController('n100')
    const mockFetch = createMockFetch(controller)
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const gatedFetch: MockFetch = async (input, init) => {
      await gate
      return mockFetch(input, init)
    }
    const client = createApiClient({
      mode: 'mock',
      baseUrl: BASE_URL,
      fetch: gatedFetch,
    })

    markAuthenticated()
    renderProvider(client)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Загрузка настроек приложения',
    )

    release()
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
  })

  it('берёт N=100 из ответа профиля n100', async () => {
    const { client } = createCountedMockClient('n100')
    markAuthenticated()

    renderProvider(client)

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
    expect(screen.getByTestId('limit')).toHaveTextContent('100')
    expect(screen.getByTestId('timezone')).toHaveTextContent('Europe/Moscow')
  })

  it('берёт N=10 из ответа профиля n10, а не из константы', async () => {
    const { client } = createCountedMockClient('n10')
    markAuthenticated()

    renderProvider(client)

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
    expect(screen.getByTestId('limit')).toHaveTextContent('10')
    expect(screen.getByTestId('limit')).not.toHaveTextContent('100')
  })

  it('достигает ready при повторном mount в StrictMode', async () => {
    const { client } = createCountedMockClient('n100')
    markAuthenticated()

    render(
      <StrictMode>
        <AppConfigProvider client={client}>
          <ConfigProbe />
        </AppConfigProvider>
      </StrictMode>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
    expect(screen.getByTestId('limit')).toHaveTextContent('100')
  })
})

describe('AppConfigProvider — ошибка и повтор', () => {
  it('на 500 сохраняет ошибку без значений по умолчанию и повторяет по кнопке', async () => {
    const controller = createController('n100')
    const mockFetch = createMockFetch(controller)
    const internalError = getExample<ErrorResponse>('error-internal-error')
    let failing = true
    const failingFetch: MockFetch = (input, init) => {
      if (failing) {
        return Promise.resolve(
          new Response(JSON.stringify(internalError), {
            status: 500,
            headers: {
              'Content-Type': 'application/json',
              'X-Request-ID': 'request-config-error',
            },
          }),
        )
      }
      return mockFetch(input, init)
    }
    const client = createApiClient({
      mode: 'mock',
      baseUrl: BASE_URL,
      fetch: failingFetch,
      retry: { maxAttempts: 1 },
    })

    markAuthenticated()
    const user = userEvent.setup()
    renderProvider(client)

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('error'),
    )
    expect(screen.getByTestId('error-code')).toHaveTextContent('INTERNAL_ERROR')
    expect(screen.getByTestId('limit')).toHaveTextContent('none')
    expect(screen.getByTestId('timezone')).toHaveTextContent('none')
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Не удалось загрузить настройки приложения',
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Идентификатор запроса: request-auth-q003-internal-500',
    )
    const retry = screen.getByRole('button', { name: 'Повторить' })
    expect(retry).toBeVisible()

    failing = false
    await user.click(retry)

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )
    expect(screen.getByTestId('limit')).toHaveTextContent('100')
  })
})

describe('AppConfigProvider — сброс приватного состояния', () => {
  it('после resetPrivateState очищает конфигурацию и возвращается в idle', async () => {
    const { client } = createCountedMockClient('n100')
    markAuthenticated()
    renderProvider(client)

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('ready'),
    )

    await act(async () => {
      resetPrivateState()
    })

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('idle'),
    )
    expect(screen.getByTestId('limit')).toHaveTextContent('none')
    expect(screen.getByTestId('timezone')).toHaveTextContent('none')
  })
})

describe('useAppConfig — границы использования', () => {
  it('вне провайдера даёт понятную ошибку', () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined)

    expect(() => render(<ConfigProbe />)).toThrow(
      'useAppConfig должен вызываться внутри AppConfigProvider.',
    )

    consoleError.mockRestore()
  })
})
