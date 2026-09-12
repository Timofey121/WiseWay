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
  BatchGate,
  ConfigProfile,
  MockControllerOptions,
  MockDictionaryOperation,
  MockPublishingOperation,
  MockSearchOperation,
  MockSearchScope,
  MockSimulationOperation,
  QuarantineGate,
  SearchFreshnessProfile,
} from './controller'
export {
  MOCK_MARKER_HEADER,
  MOCK_MODE,
  RETRY_AFTER_HEADER,
  RETRY_AFTER_SECONDS,
} from './responses'
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
  declaredSimulationErrors,
  isSimulationErrorCode,
} from './simulations/errors'
export type {
  CreateDictionarySimulationErrorCode,
  DeclaredSimulationError,
  GetSimulationErrorCode,
  MockSimulationErrorCode,
} from './simulations/errors'
export {
  declaredPublishingErrors,
  isPublishingErrorCode,
} from './publishing/errors'
export type {
  DeclaredPublishingError,
  GetDictionaryVersionErrorCode,
  ListDictionaryVersionsErrorCode,
  MockPublishingErrorCode,
  PublishDictionaryErrorCode,
  RestoreDictionaryDraftErrorCode,
} from './publishing/errors'
export {
  declaredPreviewErrors,
  declaredSelectionUseErrors,
  declaredSortingErrors,
  isPreviewErrorCode,
  isSortingErrorCode,
  isSortingErrorDeclaredForOperation,
  previewErrorResponse,
  selectionUseErrorResponse,
  sortingErrorCodesByOperation,
} from './sorting/errors'
export type {
  CreateSortingPreviewErrorCode,
  CreateSortingSelectionErrorCode,
  DeclaredSelectionUseError,
  DeclaredSortingError,
  GetSortingPreviewErrorCode,
  MockPreviewErrorCode,
  MockPreviewOperation,
  MockSortingErrorCode,
  MockSortingOperation,
  QuerySortingQueueErrorCode,
  SelectionUseErrorCode,
} from './sorting/errors'
export { QUEUE_SCENARIOS, getCannedQueueResponse } from './sorting/queue'
export type { QueueScenario } from './sorting/queue'
export {
  BATCH_PHASES,
  BATCH_SCENARIOS,
  BatchStore,
  PHASE_SCENARIO,
  bindBatchPage,
  canonicalPhase,
  getCannedBatchPage1,
  getCannedBatchPages,
  identityFromBatch,
  parseBatchLimit,
  resolveBatchHistoryPage,
  resolveCannedBatchPage,
  toBatchSummary,
} from './sorting/batch'
export type {
  BatchHistoryQuery,
  BatchIdentity,
  BatchOperationLookup,
  BatchPhase,
  BatchScenario,
  StoredBatch,
  StoredBatchOperation,
} from './sorting/batch'
export {
  batchErrorCodesByOperation,
  batchErrorResponse,
  declaredBatchErrors,
  isBatchErrorCode,
  isBatchErrorDeclaredForOperation,
} from './sorting/batch-errors'
export type {
  CreateSortingBatchErrorCode,
  DeclaredBatchError,
  GetSortingBatchErrorCode,
  ListSortingBatchesErrorCode,
  MockBatchErrorCode,
  MockBatchOperation,
} from './sorting/batch-errors'
export {
  declaredQuarantineErrors,
  isQuarantineErrorCode,
  isQuarantineErrorDeclaredForOperation,
  quarantineErrorCodesByOperation,
  quarantineErrorResponse,
  recoveryRequiredResponse,
} from './quarantine/errors'
export type {
  DeclaredQuarantineError,
  ListQuarantineItemsErrorCode,
  MockQuarantineErrorCode,
  MockQuarantineOperation,
  QuarantineErrorOptions,
  ReturnQuarantineItemErrorCode,
} from './quarantine/errors'
export {
  QUARANTINE_COMPANY_ID,
  QUARANTINE_ID,
  QUARANTINE_RECOVERY_OPERATION_ID,
  QUARANTINE_SCENARIOS,
  QuarantineStore,
  parseQuarantineLimit,
  resolveQuarantinePage,
} from './quarantine/store'
export type {
  QuarantineOperationLookup,
  QuarantineOperationOutcome,
  QuarantinePageQuery,
  QuarantineRecord,
  QuarantineScenario,
} from './quarantine/store'
export {
  auditErrorCodesByOperation,
  auditErrorResponse,
  declaredAuditErrors,
  isAuditErrorCode,
  isAuditErrorDeclaredForOperation,
} from './audit/errors'
export type {
  AuditErrorCode,
  AuditErrorOptions,
  DeclaredAuditError,
  MockAuditErrorCode,
  MockAuditOperation,
} from './audit/errors'
export {
  AUDIT_ACTORS_PAGE_ID,
  AUDIT_ATLAS_COMPANY_ID,
  AUDIT_NEWEST_EVENT_ID,
  AUDIT_QUERY_PAGE2_CURSORS,
  AUDIT_SCENARIOS,
  AUDIT_WORKER_NEWEST_EVENT_ID,
  AuditStore,
  deriveAuditScenario,
  isValidAuditInterval,
  parseAuditLimit,
} from './audit/store'
export type {
  AuditActorsQuery,
  AuditRole,
  AuditScenario,
} from './audit/store'
export {
  PREVIEW_SCENARIOS,
  PreviewStore,
  derivePreviewScenario,
  getCannedPreview,
  parsePreviewLimit,
  resolvePreviewPage,
} from './sorting/preview'
export type {
  PreviewPageQuery,
  PreviewScenario,
  StoredPreview,
} from './sorting/preview'
export {
  MAX_BATCH_ITEMS,
  SelectionStore,
  resolveSelectionCreation,
} from './sorting/selection'
export type {
  FrozenSelectionMember,
  SelectionCreation,
  SelectionCreationContext,
  SelectionResolution,
  SelectionResolveOptions,
  StoredSelection,
} from './sorting/selection'
export {
  isAllowedTarget,
  listCompanyTargets,
  resolveTargetDisplayPath,
} from './dictionaries/targets'
export type { ResolveTargetResult } from './dictionaries/targets'
export { DictionaryStore } from './dictionaries/store'
export {
  parseSimulationLimit,
  resolveSimulationPage,
  SIMULATION_SCENARIOS,
  SimulationStore,
} from './simulations/store'
export type {
  SimulationPageQuery,
  SimulationScenario,
  StoredSimulation,
} from './simulations/store'
export {
  parseVersionsLimit,
  PUBLISHING_SCENARIOS,
  PublishingStore,
  resolveVersionsPage,
} from './publishing/store'
export type {
  PublishingScenario,
  StoredPublishOperation,
  VersionPageQuery,
} from './publishing/store'
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
