// Публичная точка входа mock-инфраструктуры WiseWay (LT-06.1).
//
// `createMockFetch(controller?)` возвращает fetch-совместимую функцию, которую
// транспорт принимает в `createApiClient({ mode: 'mock', fetch })`. Схемы
// запросов/ответов — те же generated-типы единственного OAS, что и в
// real-режиме; подменяется только транспорт.
//
// Mock обслуживает только bootstrap/session/config операции без backend:
// health, login, getSession, logout, getAppConfig, listRoots, listCompanies.
// Он не является защищённым auth backend: реальные credentials, cookie-сессии
// и серверные проверки отсутствуют, а пароли в примерах — инертные
// placeholder'ы.
//
// @example
// import { createApiClient } from '@/api/transport'
// import { createMockFetch, MockController } from '@/mocks'
//
// const controller = new MockController()
// const api = createApiClient({ mode: 'mock', fetch: createMockFetch(controller) })

import { MockController } from './controller'
import { routeMockRequest } from './router'

export { MockController }
export type {
  ConfigProfile,
  MockControllerOptions,
} from './controller'
export { MOCK_MODE, MOCK_MARKER_HEADER } from './responses'
export type {
  MockHandler,
  MockRequestContext,
} from './types'

/** Fetch-совместимая подпись mock-перехватчика. */
export type MockFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>

/**
 * Создаёт fetch-совместимый mock-перехватчик с собственным (или переданным)
 * контроллером сценариев.
 */
export function createMockFetch(
  controller: MockController = new MockController(),
): MockFetch {
  return async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    return routeMockRequest(request, controller)
  }
}
