// Реестр mock-handlers bootstrap/session/config: `METHOD path` → handler.
//
// Набор ограничен операциями LT-06.1. Неизвестный маршрут в router даёт
// безопасную 404, а не правдоподобный успех.

import type { MockHandler } from '../types'
import { loginHandler, logoutHandler, sessionHandler } from './auth'
import { companiesHandler, rootsHandler } from './catalog'
import { appConfigHandler } from './config'
import { healthHandler } from './health'

export const handlersByKey: Record<string, MockHandler> = {
  'GET /health': healthHandler,
  'POST /auth/login': loginHandler,
  'GET /session': sessionHandler,
  'POST /auth/logout': logoutHandler,
  'GET /app-config': appConfigHandler,
  'GET /roots': rootsHandler,
  'GET /companies': companiesHandler,
}
