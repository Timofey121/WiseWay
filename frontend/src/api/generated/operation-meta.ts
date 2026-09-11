// Этот файл сгенерирован scripts/generate-api.mjs из
// contracts/openapi/wiseway-v1.yaml. Не редактируется вручную: изменения
// будут перезаписаны следующей генерацией `npm run generate:api`.
//
// `csrf`/`idempotencyKey` выведены из наличия `$ref` на
// #/components/parameters/XCSRFToken и #/components/parameters/IdempotencyKey.

export interface OperationMeta {
  /** operationId операции в публичном OAS. */
  operationId: string
  /** Требует ли операция заголовок X-CSRF-Token. */
  csrf: boolean
  /** Требует ли операция заголовок Idempotency-Key. */
  idempotencyKey: boolean
}

export const operationMeta = {
  'GET /health': { operationId: 'getHealth', csrf: false, idempotencyKey: false },
  'POST /auth/login': { operationId: 'login', csrf: false, idempotencyKey: false },
  'GET /session': { operationId: 'getSession', csrf: false, idempotencyKey: false },
  'POST /auth/logout': { operationId: 'logout', csrf: true, idempotencyKey: false },
  'GET /app-config': { operationId: 'getAppConfig', csrf: false, idempotencyKey: false },
  'GET /roots': { operationId: 'listRoots', csrf: false, idempotencyKey: false },
  'GET /companies': { operationId: 'listCompanies', csrf: false, idempotencyKey: false },
  'POST /search': { operationId: 'searchFiles', csrf: false, idempotencyKey: false },
  'POST /search/facet': { operationId: 'getSearchFacet', csrf: false, idempotencyKey: false },
  'GET /companies/{company_id}/target-directories': { operationId: 'listTargetDirectories', csrf: false, idempotencyKey: false },
  'POST /companies/{company_id}/target-directories/resolve': { operationId: 'resolveTargetDirectory', csrf: false, idempotencyKey: false },
  'GET /companies/{company_id}/dictionaries': { operationId: 'listDictionaries', csrf: false, idempotencyKey: false },
  'POST /companies/{company_id}/dictionaries': { operationId: 'createDictionary', csrf: true, idempotencyKey: false },
  'GET /dictionaries/{dictionary_id}': { operationId: 'getDictionary', csrf: false, idempotencyKey: false },
  'PUT /dictionaries/{dictionary_id}/draft': { operationId: 'replaceDictionaryDraft', csrf: true, idempotencyKey: false },
  'GET /dictionaries/{dictionary_id}/versions': { operationId: 'listDictionaryVersions', csrf: false, idempotencyKey: false },
  'GET /dictionaries/{dictionary_id}/versions/{version_id}': { operationId: 'getDictionaryVersion', csrf: false, idempotencyKey: false },
  'POST /dictionaries/{dictionary_id}/restore-draft': { operationId: 'restoreDictionaryDraft', csrf: true, idempotencyKey: false },
  'POST /dictionaries/{dictionary_id}/simulate': { operationId: 'createDictionarySimulation', csrf: true, idempotencyKey: false },
  'GET /simulations/{simulation_id}': { operationId: 'getSimulation', csrf: false, idempotencyKey: false },
  'POST /dictionaries/{dictionary_id}/publish': { operationId: 'publishDictionary', csrf: true, idempotencyKey: true },
  'POST /sorting/queue/query': { operationId: 'querySortingQueue', csrf: false, idempotencyKey: false },
  'POST /sorting/selections': { operationId: 'createSortingSelection', csrf: true, idempotencyKey: false },
  'POST /sorting/previews': { operationId: 'createSortingPreview', csrf: true, idempotencyKey: false },
  'GET /sorting/previews/{preview_id}': { operationId: 'getSortingPreview', csrf: false, idempotencyKey: false },
  'GET /sorting/batches': { operationId: 'listSortingBatches', csrf: false, idempotencyKey: false },
  'POST /sorting/batches': { operationId: 'createSortingBatch', csrf: true, idempotencyKey: true },
  'GET /sorting/batches/{batch_id}': { operationId: 'getSortingBatch', csrf: false, idempotencyKey: false },
  'GET /quarantine': { operationId: 'listQuarantineItems', csrf: false, idempotencyKey: false },
  'POST /quarantine/{quarantine_id}/return': { operationId: 'returnQuarantineItem', csrf: true, idempotencyKey: true },
  'POST /audit/query': { operationId: 'queryAuditEvents', csrf: false, idempotencyKey: false },
  'GET /audit/updates': { operationId: 'getAuditUpdates', csrf: false, idempotencyKey: false },
  'GET /audit/actors': { operationId: 'listAuditActors', csrf: false, idempotencyKey: false },
} as const satisfies Record<string, OperationMeta>

export type OperationMetaKey = keyof typeof operationMeta
