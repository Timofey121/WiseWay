// Реестр mock-handlers bootstrap/session/config, поиска, targets/dictionaries и
// симуляции: `METHOD path` → handler.
//
// Набор ограничен операциями LT-06.1 (bootstrap/session/config), LT-06.2a-ii
// (`searchFiles`/`getSearchFacet`), LT-07.1a (targets/dictionaries) и LT-07.1b
// (`createDictionarySimulation`/`getSimulation`), LT-07.1c
// (publish/versions/restore), LT-07.2a (`querySortingQueue`/
// `createSortingSelection`), LT-07.2b (`createSortingPreview`/
// `getSortingPreview`) и LT-07.2c (`createSortingBatch`/`getSortingBatch`/
// `listSortingBatches`), а также LT-07.3a (`listQuarantineItems`/
// `returnQuarantineItem`) и LT-07.3b (`queryAuditEvents`/`getAuditUpdates`/
// `listAuditActors`). Пути с `{param}`
// (company_id/dictionary_id/version_id/simulation_id/preview_id/batch_id/
// quarantine_id) сопоставляются router'ом.
// Неизвестный маршрут в router даёт безопасную 404, а не правдоподобный успех.

import type { MockHandler } from '../types'
import {
  getAuditUpdatesHandler,
  listAuditActorsHandler,
  queryAuditEventsHandler,
} from './audit'
import { loginHandler, logoutHandler, sessionHandler } from './auth'
import {
  createSortingBatchHandler,
  getSortingBatchHandler,
  listSortingBatchesHandler,
} from './batches'
import { companiesHandler, rootsHandler } from './catalog'
import { appConfigHandler } from './config'
import {
  createDictionaryHandler,
  getDictionaryHandler,
  listDictionariesHandler,
  replaceDictionaryDraftHandler,
} from './dictionaries'
import { healthHandler } from './health'
import {
  listQuarantineItemsHandler,
  returnQuarantineItemHandler,
} from './quarantine'
import {
  getDictionaryVersionHandler,
  listDictionaryVersionsHandler,
  publishDictionaryHandler,
  restoreDictionaryDraftHandler,
} from './publishing'
import {
  createSortingPreviewHandler,
  getSortingPreviewHandler,
} from './previews'
import { searchFacetHandler, searchHandler } from './search'
import {
  createDictionarySimulationHandler,
  getSimulationHandler,
} from './simulations'
import {
  createSortingSelectionHandler,
  querySortingQueueHandler,
} from './sorting'
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
  'GET /dictionaries/{dictionary_id}/versions': listDictionaryVersionsHandler,
  'GET /dictionaries/{dictionary_id}/versions/{version_id}':
    getDictionaryVersionHandler,
  'POST /dictionaries/{dictionary_id}/restore-draft':
    restoreDictionaryDraftHandler,
  'POST /dictionaries/{dictionary_id}/publish': publishDictionaryHandler,
  'POST /dictionaries/{dictionary_id}/simulate':
    createDictionarySimulationHandler,
  'GET /simulations/{simulation_id}': getSimulationHandler,
  'POST /sorting/queue/query': querySortingQueueHandler,
  'POST /sorting/selections': createSortingSelectionHandler,
  'POST /sorting/previews': createSortingPreviewHandler,
  'GET /sorting/previews/{preview_id}': getSortingPreviewHandler,
  'POST /sorting/batches': createSortingBatchHandler,
  'GET /sorting/batches': listSortingBatchesHandler,
  'GET /sorting/batches/{batch_id}': getSortingBatchHandler,
  'GET /quarantine': listQuarantineItemsHandler,
  'POST /quarantine/{quarantine_id}/return': returnQuarantineItemHandler,
  'POST /audit/query': queryAuditEventsHandler,
  'GET /audit/updates': getAuditUpdatesHandler,
  'GET /audit/actors': listAuditActorsHandler,
}
