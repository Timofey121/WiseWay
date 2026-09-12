import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App'
import { resetSessionState } from '../src/app/session-state'

beforeEach(() => {
  resetSessionState()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('отображает оболочку с заголовком WiseWay', () => {
    render(<App />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'WiseWay',
    )
  })

  it('в анонимном состоянии не запрашивает app-config', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    render(<App />)

    expect(
      screen.getByRole('navigation', { name: 'Разделы приложения' }),
    ).toBeVisible()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
