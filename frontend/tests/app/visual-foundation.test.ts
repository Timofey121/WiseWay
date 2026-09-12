// LT-E03-VR1: единый visual foundation WiseWay.
//
// Проверяется, что foundation реально задаёт токены/примитивы, что оболочка и
// login/session CSS потребляют одну систему (токены и общие классы), а не
// дублируют ad-hoc палитру, и что foundation импортируется первым.

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8')
}

/** Извлекает hex-значение CSS-токена из исходника foundation. */
function extractHexToken(css: string, name: string): string {
  const match = css.match(new RegExp(`${name}\\s*:\\s*(#[0-9a-fA-F]{6})`))
  if (!match) {
    throw new Error(`Токен ${name} не найден в foundation.css`)
  }
  return match[1]
}

/** Относительная яркость цвета по WCAG 2.1. */
function relativeLuminance(hex: string): number {
  const value = hex.replace('#', '')
  const channels = [0, 2, 4].map((offset) => {
    const channel = parseInt(value.slice(offset, offset + 2), 16) / 255
    return channel <= 0.03928
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

/** Коэффициент контраста двух цветов по WCAG 2.1 (от 1 до 21). */
function contrastRatio(a: string, b: string): number {
  const luminanceA = relativeLuminance(a)
  const luminanceB = relativeLuminance(b)
  const lighter = Math.max(luminanceA, luminanceB)
  const darker = Math.min(luminanceA, luminanceB)
  return (lighter + 0.05) / (darker + 0.05)
}

const foundationCss = readSource('src/styles/foundation.css')
const shellCss = readSource('src/app/shell.css')
const authCss = readSource('src/features/auth/auth.css')
const shellSource = readSource('src/app/AppShell.tsx')
const loginSource = readSource('src/features/auth/login-screen.tsx')
const sessionStatesSource = readSource('src/features/auth/session-states.tsx')
const mainSource = readSource('src/main.tsx')

describe('Visual foundation — токены', () => {
  it('объявляет типографику, нейтральную палитру, акцент и статусы', () => {
    for (const token of [
      '--ww-font-sans',
      '--ww-font-size-base',
      '--ww-line-height-base',
      '--ww-color-bg',
      '--ww-color-surface',
      '--ww-color-border',
      '--ww-color-text',
      '--ww-color-text-muted',
      '--ww-color-accent',
      '--ww-color-accent-hover',
      '--ww-color-accent-active',
      '--ww-color-error-text',
      '--ww-color-warning-text',
      '--ww-color-info-text',
      '--ww-space-4',
      '--ww-radius-md',
      '--ww-shadow-sm',
      '--ww-focus-ring-color',
    ]) {
      expect(foundationCss).toContain(token)
    }
  })

  it('задаёт базовый reset: box-sizing, body без отступа и нейтральный фон', () => {
    expect(foundationCss).toContain('box-sizing: border-box')
    expect(foundationCss).toMatch(/body\s*\{[^}]*margin:\s*0/s)
    expect(foundationCss).toMatch(
      /body\s*\{[^}]*background:\s*var\(--ww-color-bg\)/s,
    )
  })

  it('граница компонентов контрастна к поверхности (WCAG 2.1 SC 1.4.11)', () => {
    const borderStrong = extractHexToken(
      foundationCss,
      '--ww-color-border-strong',
    )
    const surface = extractHexToken(foundationCss, '--ww-color-surface')
    const ratio = contrastRatio(borderStrong, surface)

    // Границы полей ввода/компонентов должны читаться как UI-граница: >= 3:1.
    expect(ratio).toBeGreaterThanOrEqual(3.0)
  })
})

describe('Visual foundation — общие примитивы', () => {
  it('предоставляет кнопки, поля, поверхности, бейджи, алерты и вкладки', () => {
    for (const primitive of [
      '.ww-button',
      '.ww-button--primary',
      '.ww-button--secondary',
      '.ww-input',
      '.ww-surface',
      '.ww-card',
      '.ww-badge',
      '.ww-alert',
      '.ww-alert--error',
      '.ww-status',
      '.ww-nav__button',
      '.ww-empty',
    ]) {
      expect(foundationCss).toContain(primitive)
    }
  })

  it('задаёт единый focus-visible контур', () => {
    expect(foundationCss).toContain(':focus-visible')
    expect(foundationCss).toContain('outline')
    expect(foundationCss).toContain('var(--ww-focus-ring-width)')
  })
})

describe('Visual foundation — одна система для login и оболочки', () => {
  it('оболочка потребляет токены и общие вкладки', () => {
    expect(shellCss).toContain('var(--ww-')
    expect(shellSource).toContain('ww-nav__button')
    // Тест LT-08.1 ожидает видимый фокус именно в shell.css.
    expect(shellCss).toContain(':focus-visible')
    expect(shellCss).toContain('outline')
  })

  it('login и состояния сессии потребляют токены и общие примитивы', () => {
    expect(authCss).toContain('var(--ww-')
    expect(loginSource).toContain('ww-card')
    expect(loginSource).toContain('ww-button')
    expect(loginSource).toContain('ww-input')
    expect(sessionStatesSource).toContain('ww-alert')
  })

  it('foundation импортируется первым, до прикладных стилей', () => {
    const foundationIndex = mainSource.indexOf("'./styles/foundation.css'")
    const shellIndex = mainSource.indexOf("'./app/shell.css'")
    const authIndex = mainSource.indexOf("'./features/auth/auth.css'")

    expect(foundationIndex).toBeGreaterThanOrEqual(0)
    expect(shellIndex).toBeGreaterThan(foundationIndex)
    expect(authIndex).toBeGreaterThan(shellIndex)
  })
})
