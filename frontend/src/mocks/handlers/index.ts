// Реестр mock-handlers bootstrap/session/config и поиска: `METHOD path` → handler.
//
// Набор ограничен операциями LT-06.1 (bootstrap/session/config) и LT-06.2a-ii
// (`searchFiles`/`getSearchFacet`). Неизвестный маршрут в router даёт безопасную
// 404, а не правдоподобный успех.

import type { MockHandler } from '../types'
import { loginHandler, logoutHandler, sessionHandler } from './auth'
import { companiesHandler, rootsHandler } from './catalog'
import { appConfigHandler } from './config'
import { healthHandler } from './health'
import { searchFacetHandler, searchHandler } from './search'

export const handlersByKey: Record<string, MockHandler> = {
  'GET /health': healthHandler,
  'POST /auth/login': loginHandler,
  'GET /session': sessionHandler,
  'POST /auth/logout': logoutHandler,
  'GET /app-config': appConfigHandler,
  'GET /roots': rootsHandler,
  'GET /companies': companiesHandler,
  'POST /search': searchHandler,
  'POST /search/facet': searchFacetHandler,
}
