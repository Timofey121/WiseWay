// Публичная точка входа mock-инфраструктуры WiseWay (LT-06.1).
//
// `createMockFetch(controller?)` возвращает fetch-совместимую функцию, которую
// транспорт принимает в `createApiClient({ mode: 'mock', fetch })`. Схемы
// запросов/ответов — те же generated-типы единственного OAS, что и в
// real-режиме; подменяется только транспорт.
//
// Mock обслуживает только операции без backend: bootstrap/session/config
// (health, login, getSession, logout, getAppConfig, listRoots, listCompanies) и
// golden-поиск (searchFiles, getSearchFacet). Он не является защищённым auth
// backend: реальные credentials, cookie-сессии и серверные проверки
// отсутствуют, а пароли в примерах — инертные placeholder'ы. Поиск не
// выполняет matcher/ranking: handler отдаёт literal golden-ответ либо
// объявленную ошибку.
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
  MockDictionaryOperation,
  MockSearchOperation,
  MockSearchScope,
  SearchFreshnessProfile,
} from './controller'
export { MOCK_MODE, MOCK_MARKER_HEADER } from './responses'
export {
  declaredSearchErrors,
  isSearchErrorCode,
} from './search/errors'
export type { DeclaredSearchError, SearchErrorCode } from './search/errors'
export {
  declaredDictionaryErrors,
  isDictionaryErrorCode,
} from './dictionaries/errors'
export type {
  DeclaredDictionaryError,
  MockDictionaryErrorCode,
} from './dictionaries/errors'
export {
  isAllowedTarget,
  listCompanyTargets,
  resolveTargetDisplayPath,
} from './dictionaries/targets'
export type { ResolveTargetResult } from './dictionaries/targets'
export { DictionaryStore } from './dictionaries/store'
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
