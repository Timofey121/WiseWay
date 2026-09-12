// LT-08.1: оболочка приложения, навигация по разделам и гарантии отсутствия
// скрытых действий. Проверяются состав/порядок разделов, стартовый «Поиск»,
// доступность мышью и клавиатурой, видимый/семантический фокус, честные
// заглушки, отсутствие сетевых запросов и отсутствие записи в URL/history/
// storage/cookie.

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from '@/app/index'

const shellCss = readFileSync(
  resolve(process.cwd(), 'src/app/shell.css'),
  'utf8',
)

const sectionLabels = [
  'Поиск',
  'Справочники',
  'Очередь сортировки',
  'Карантин',
  'Журнал',
] as const

function getNav() {
  return screen.getByRole('navigation', { name: 'Разделы приложения' })
}

function getNavButtons(): HTMLElement[] {
  return within(getNav()).getAllByRole('button')
}

/**
 * Перехватывает записи в `document.cookie`, не ломая реальное значение.
 * Возвращает массив записанных значений.
 */
function spyOnCookieWrites(): string[] {
  const writes: string[] = []
  const descriptor = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(document) as object,
    'cookie',
  )

  if (!descriptor?.get || !descriptor.set) {
    throw new Error('Не удалось перехватить document.cookie в jsdom.')
  }

  Object.defineProperty(document, 'cookie', {
    configurable: true,
    get: () => descriptor.get?.call(document) as string,
    set: (value: string) => {
      writes.push(value)
      descriptor.set?.call(document, value)
    },
  })

  return writes
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'cookie')
})

describe('AppShell — состав и навигация', () => {
  it('отображает ровно пять разделов в заданном порядке', () => {
    render(<AppShell />)

    expect(getNavButtons().map((button) => button.textContent)).toEqual([
      ...sectionLabels,
    ])
  })

  it('стартовым разделом является «Поиск»', () => {
    render(<AppShell />)

    const searchButton = screen.getByRole('button', { name: 'Поиск' })
    expect(searchButton).toHaveAttribute('aria-current', 'page')
    for (const label of sectionLabels.slice(1)) {
      expect(screen.getByRole('button', { name: label })).not.toHaveAttribute(
        'aria-current',
      )
    }

    expect(
      screen.getByRole('heading', { level: 2, name: 'Поиск' }),
    ).toBeVisible()
  })

  it('переключает раздел по клику и переносит aria-current', async () => {
    const user = userEvent.setup()
    render(<AppShell />)

    await user.click(screen.getByRole('button', { name: 'Справочники' }))

    expect(
      screen.getByRole('button', { name: 'Справочники' }),
    ).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Поиск' })).not.toHaveAttribute(
      'aria-current',
    )
    expect(
      screen.getByRole('heading', { level: 2, name: 'Справочники' }),
    ).toBeVisible()
  })

  it('достигает каждого раздела клавишей Tab', async () => {
    const user = userEvent.setup()
    render(<AppShell />)

    for (const label of sectionLabels) {
      await user.tab()
      expect(document.activeElement).toHaveTextContent(label)
    }
  })

  it('активирует раздел клавишами Enter и Space', async () => {
    const user = userEvent.setup()
    render(<AppShell />)

    await user.tab() // «Поиск»
    await user.tab() // «Справочники»
    await user.keyboard('{Enter}')
    expect(
      screen.getByRole('button', { name: 'Справочники' }),
    ).toHaveAttribute('aria-current', 'page')

    await user.tab() // «Очередь сортировки»
    await user.keyboard(' ')
    expect(
      screen.getByRole('button', { name: 'Очередь сортировки' }),
    ).toHaveAttribute('aria-current', 'page')
  })

  it('обозначает фокус клавиатуры видимым стилем', () => {
    expect(shellCss).toContain(':focus-visible')
    expect(shellCss).toContain('outline')
  })

  it('показывает честные заглушки для всех разделов', async () => {
    const user = userEvent.setup()
    render(<AppShell />)

    for (const label of sectionLabels) {
      await user.click(screen.getByRole('button', { name: label }))

      const region = screen.getByRole('region', { name: label })
      expect(
        within(region).getByRole('heading', { level: 2 }),
      ).toHaveTextContent(label)
      expect(
        within(region).getByText('Раздел ещё не реализован'),
      ).toBeVisible()
      // Заглушка не изображает рабочий продукт: без выдуманных чисел/итогов.
      expect(region.textContent ?? '').not.toMatch(/\d/)
    }
  })
})

describe('AppShell — отсутствие скрытых действий', () => {
  it('не выполняет сетевых запросов при переключении разделов', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const xhrOpenSpy = vi.spyOn(window.XMLHttpRequest.prototype, 'open')

    render(<AppShell />)
    for (const label of sectionLabels) {
      await user.click(screen.getByRole('button', { name: label }))
    }

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpenSpy).not.toHaveBeenCalled()
  })

  it('не пишет состояние в URL, history, storage и cookie', async () => {
    const user = userEvent.setup()
    const setItemSpy = vi.spyOn(window.Storage.prototype, 'setItem')
    const removeItemSpy = vi.spyOn(window.Storage.prototype, 'removeItem')
    const clearSpy = vi.spyOn(window.Storage.prototype, 'clear')
    const pushStateSpy = vi.spyOn(window.history, 'pushState')
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
    const cookieWrites = spyOnCookieWrites()
    const initialHref = window.location.href
    const initialHistoryState = window.history.state

    render(<AppShell />)
    for (const label of sectionLabels) {
      await user.click(screen.getByRole('button', { name: label }))
    }

    expect(window.location.href).toBe(initialHref)
    expect(window.history.state).toBe(initialHistoryState)
    expect(pushStateSpy).not.toHaveBeenCalled()
    expect(replaceStateSpy).not.toHaveBeenCalled()
    expect(setItemSpy).not.toHaveBeenCalled()
    expect(removeItemSpy).not.toHaveBeenCalled()
    expect(clearSpy).not.toHaveBeenCalled()
    expect(cookieWrites).toEqual([])
  })
})
