// Единая фабрика app-level API-клиента WiseWay.
//
// Режим транспорта выбирается ТОЛЬКО на этапе сборки через
// `import.meta.env.VITE_API_MODE`:
// - точное значение `'mock'` → `createApiClient({ mode: 'mock', fetch:
//   createMockFetch() })`;
// - любое другое значение (включая отсутствие переменной) → `real`.
//
// Молчаливого отката в mock нет: неизвестное/пустое значение означает real.
// UI-компоненты не создают транспорт напрямую — они получают клиент от
// `AppConfigProvider` (и, далее, от других app-level провайдеров).
//
// `createAppApiClient(mode)` принимает явный режим для тестов; в приложении
// аргумент не передаётся, поэтому фактический режим определяется env.
//
// Браузерный тестовый шов: в mock-режиме (только для сборки browser-проверок)
// глобальное `globalThis.__WISEWAY_TEST_FETCH__` может подменить mock-fetch,
// чтобы Playwright воспроизвёл сетевой сбой/5xx при старте. В real-режиме шов
// игнорируется и на прод не влияет.

import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import { createMockFetch } from '@/mocks'

/** Режим транспорта приложения. */
export type AppApiMode = 'real' | 'mock'

/** Fetch-совместимая подпись транспорта. */
export type AppApiFetch = (
  input: Request,
  init?: RequestInit,
) => Promise<Response>

/** Имя браузерного тестового шва (mock-режим). */
export const TEST_FETCH_GLOBAL = '__WISEWAY_TEST_FETCH__'

/**
 * Разрешает значение `VITE_API_MODE` в режим транспорта. `'mock'` — только
 * точное совпадение; всё остальное — `'real'`.
 */
export function resolveAppApiMode(value: unknown): AppApiMode {
  return value === 'mock' ? 'mock' : 'real'
}

/**
 * Читает браузерный тестовый fetch-шов. Используется только в mock-режиме;
 * значение не персистится и живёт в памяти страницы.
 */
export function readTestFetchOverride(): AppApiFetch | undefined {
  const value = (globalThis as Record<string, unknown>)[TEST_FETCH_GLOBAL]
  return typeof value === 'function' ? (value as AppApiFetch) : undefined
}

/**
 * Абсолютный baseUrl `/api/v1` текущего origin. В браузере относительный путь
 * эквивалентен, но абсолютный origin делает транспорт воспроизводимым и в
 * jsdom (где `new Request()` не принимает относительный URL), не меняя
 * same-origin семантику. Без `location` используется относительный путь из OAS.
 */
export function defaultAppBaseUrl(): string {
  const origin = (globalThis as { location?: { origin?: unknown } }).location
    ?.origin
  return typeof origin === 'string' && origin.length > 0 && origin !== 'null'
    ? `${origin}/api/v1`
    : '/api/v1'
}

/**
 * Создаёт app-level API-клиент в выбранном режиме.
 *
 * @param mode режим транспорта; по умолчанию берётся из `VITE_API_MODE`.
 * @param fetchOverride тестовый шов для mock-режима (браузерные проверки).
 */
export function createAppApiClient(
  mode: AppApiMode = resolveAppApiMode(import.meta.env.VITE_API_MODE),
  fetchOverride: AppApiFetch | undefined = readTestFetchOverride(),
): WiseWayApiClient {
  const baseUrl = defaultAppBaseUrl()
  if (mode === 'mock') {
    return createApiClient({
      mode: 'mock',
      baseUrl,
      fetch: fetchOverride ?? createMockFetch(),
    })
  }
  return createApiClient({ mode: 'real', baseUrl })
}
