// Реестр mock-handlers bootstrap/session/config, поиска и targets/dictionaries:
// `METHOD path` → handler.
//
// Набор ограничен операциями LT-06.1 (bootstrap/session/config), LT-06.2a-ii
// (`searchFiles`/`getSearchFacet`) и LT-07.1a (targets/dictionaries). Пути с
// `{param}` (company_id/dictionary_id) сопоставляются router'ом. Неизвестный
// маршрут в router даёт безопасную 404, а не правдоподобный успех.

import type { MockHandler } from '../types'
import { loginHandler, logoutHandler, sessionHandler } from './auth'
import { companiesHandler, rootsHandler } from './catalog'
import { appConfigHandler } from './config'
import {
  createDictionaryHandler,
  getDictionaryHandler,
  listDictionariesHandler,
  replaceDictionaryDraftHandler,
} from './dictionaries'
import { healthHandler } from './health'
import { searchFacetHandler, searchHandler } from './search'
import {
  listTargetDirectoriesHandler,
  resolveTargetDirectoryHandler,
} from './targets'

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
  'GET /companies/{company_id}/target-directories': listTargetDirectoriesHandler,
  'POST /companies/{company_id}/target-directories/resolve':
    resolveTargetDirectoryHandler,
  'GET /companies/{company_id}/dictionaries': listDictionariesHandler,
  'POST /companies/{company_id}/dictionaries': createDictionaryHandler,
  'GET /dictionaries/{dictionary_id}': getDictionaryHandler,
  'PUT /dictionaries/{dictionary_id}/draft': replaceDictionaryDraftHandler,
}
