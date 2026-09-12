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

import { createApiClient, type WiseWayApiClient } from '@/api/transport'
import { createMockFetch } from '@/mocks'

/** Режим транспорта приложения. */
export type AppApiMode = 'real' | 'mock'

/**
 * Разрешает значение `VITE_API_MODE` в режим транспорта. `'mock'` — только
 * точное совпадение; всё остальное — `'real'`.
 */
export function resolveAppApiMode(value: unknown): AppApiMode {
  return value === 'mock' ? 'mock' : 'real'
}

/**
 * Создаёт app-level API-клиент в выбранном режиме.
 *
 * @param mode режим транспорта; по умолчанию берётся из `VITE_API_MODE`.
 */
export function createAppApiClient(
  mode: AppApiMode = resolveAppApiMode(import.meta.env.VITE_API_MODE),
): WiseWayApiClient {
  if (mode === 'mock') {
    return createApiClient({ mode: 'mock', fetch: createMockFetch() })
  }
  return createApiClient({ mode: 'real' })
}
