// POST /sorting/batches (createSortingBatch),
// GET /sorting/batches (listSortingBatches) и
// GET /sorting/batches/{batch_id} (getSortingBatch) — LT-07.2c.
//
// Операции отдают literal canned-сценарии из
// `contracts/examples/sorting/batch-*.json` и
// `contracts/examples/sorting/batch-history-atlas-page1.json`. Mock не
// выполняет claim, executor, matcher, перемещение файлов, подсчёт progress и
// recovery: он проверяет входные поля, воспроизводит объявленные gates и
// выбирает заранее заданный сценарий/фазу контроллера.
//
// `createSortingBatch` — объявленная мутация (`csrf: true`,
// `idempotencyKey: true`): требует активную mock-сессию, корректный
// `X-CSRF-Token` и непустой `Idempotency-Key`, валидирует
// `BatchCreateRequest` (oneOf DIRECT/PREVIEWED; PREVIEWED требует
// `preview_id`, DIRECT — нет). Gates объявлены контрактом:
//  * неизвестный selection/preview → 404 `NOT_FOUND`;
//  * другой owner → 403 `FORBIDDEN`;
//  * истёкший selection → 409 `SELECTION_EXPIRED`;
//  * preview другой пары/компании → 409 `INVALID_STATE`;
//  * DIRECT с изменённым источником → 409 `SELECTION_CHANGED`;
//  * PREVIEWED с устаревшим preview → 409 `STALE_PREVIEW`;
//  * превышен предел партии → 422 `VALIDATION_ERROR` (OAS `ValidationError`).
// Успех — 202 literal `Batch` (page1 выбранного сценария); 202 означает
// принятие, а не завершение.
//
// Идемпотентность scoped по actor+ключу: повтор того же ключа/тела возвращает
// прежнюю партию **до** staleness-проверок (API §2, потерянный ответ); другое
// тело с тем же ключом → 409 `IDEMPOTENCY_KEY_REUSED`; новый ключ создаёт
// новую партию (уникальный `batch_id`).
//
// `getSortingBatch` — чтение: требует только активную mock-сессию, отдаёт
// literal-страницу текущей фазы (page1/page2 через непрозрачный `cursor`),
// неизвестный `batch_id` → 404 `NOT_FOUND`, невалидный `cursor`/`limit` → 422.
// 409 у чтения не объявлен и не возвращается; recovery-партия остаётся
// незавершённой (`finished_at=null`, `recovery_required>0`).
//
// `listSortingBatches` — чтение: `company_id` обязателен, отдаёт
// `BatchSummary` компании в порядке `created_at DESC`, `batch_id DESC`;
// `cursor`/`limit` finite, невалидные → 422.

import { readJsonBody } from '../body'
import { cloneJson } from '../data'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  notFoundResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import { batchErrorResponse } from '../sorting/batch-errors'
import {
  bindBatchPage,
  getCannedBatchPage1,
  parseBatchLimit,
  PHASE_SCENARIO,
  resolveBatchHistoryPage,
  resolveCannedBatchPage,
  type BatchIdentity,
  type BatchScenario,
  type StoredBatch,
} from '../sorting/batch'
import type { BatchCreateRequest, MockHandler } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы. */
const CURSOR_ERROR = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
} as const

/** 422, если обязательный заголовок `Idempotency-Key` отсутствует. */
function missingIdempotencyKeyResponse(requestId: string): Response {
  return validationErrorResponse(requestId, [
    {
      field: 'Idempotency-Key',
      code: 'REQUIRED',
      message: 'Заголовок Idempotency-Key обязателен.',
    },
  ])
}

/** 422, если обязательный query-параметр `company_id` отсутствует. */
function missingCompanyIdResponse(requestId: string): Response {
  return validationErrorResponse(requestId, [
    {
      field: 'company_id',
      code: 'REQUIRED',
      message: 'Параметр company_id обязателен.',
    },
  ])
}

/** 422, если превышен предел одной партии (OAS `ValidationError`). */
function batchLimitExceededResponse(requestId: string): Response {
  return validationErrorResponse(requestId, [
    {
      field: 'selection_id',
      code: 'BATCH_LIMIT_EXCEEDED',
      message: 'Выбранных файлов больше, чем допустимо для одной партии.',
    },
  ])
}

/**
 * Сценарий успешного создания: явный override контроллера либо вывод из
 * `execution_mode` (DIRECT → `direct-fresh`, PREVIEWED → `previewed-fresh`).
 */
function resolveCreateScenario(
  override: BatchScenario | null,
  executionMode: BatchCreateRequest['execution_mode'],
): BatchScenario {
  if (override !== null) {
    return override
  }
  return executionMode === 'DIRECT' ? 'direct-fresh' : 'previewed-fresh'
}

/**
 * Сценарий чтения: override контроллера, затем фаза прогресса, затем
 * канонический сценарий сохранённой партии.
 */
function resolveReadScenario(
  controllerScenario: BatchScenario | null,
  controllerPhase: keyof typeof PHASE_SCENARIO | null,
  stored: StoredBatch,
): BatchScenario {
  if (controllerScenario !== null) {
    return controllerScenario
  }
  if (controllerPhase !== null) {
    return PHASE_SCENARIO[controllerPhase]
  }
  return stored.scenario
}

/**
 * POST /sorting/batches
 * → 202 Batch (literal canned) | 401 | 403 | 404 | 409 | 422 | управляемая
 * ошибка. Идемпотентный replay идёт до staleness-проверок.
 */
export const createSortingBatchHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('BatchCreateRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const idempotencyKey = request.headers.get('Idempotency-Key')
  if (!idempotencyKey || idempotencyKey.trim().length === 0) {
    return missingIdempotencyKeyResponse(requestId)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const payload = body.value as BatchCreateRequest
  const store = controller.getBatchStore()

  // Ключ проверяется до staleness-проверок: потерянный ответ принятой партии
  // должен воспроизводиться даже при устаревшем selection/preview.
  const lookup = store.resolveOperation(actor.user_id, idempotencyKey, body.value)
  if (lookup) {
    if (lookup.kind === 'replay') {
      return jsonResponse(cloneJson(lookup.stored.response), requestId, 202)
    }
    return batchErrorResponse(requestId, 'createSortingBatch', 'IDEMPOTENCY_KEY_REUSED')
  }

  const forcedError = controller.consumeBatchError('createSortingBatch')
  if (forcedError) {
    return batchErrorResponse(requestId, 'createSortingBatch', forcedError)
  }

  const resolution = controller.getSelectionStore().resolve(payload.selection_id, {
    actorId: actor.user_id,
    now: controller.getSelectionNow(),
  })
  if (resolution.kind === 'not_found') {
    return batchErrorResponse(requestId, 'createSortingBatch', 'NOT_FOUND')
  }
  if (resolution.kind === 'forbidden') {
    return batchErrorResponse(requestId, 'createSortingBatch', 'FORBIDDEN')
  }
  if (resolution.kind === 'expired') {
    return batchErrorResponse(requestId, 'createSortingBatch', 'SELECTION_EXPIRED')
  }

  const gate = controller.getBatchGate()
  if (gate === 'BATCH_LIMIT_EXCEEDED') {
    return batchLimitExceededResponse(requestId)
  }

  const selection = resolution.selection
  if (payload.execution_mode === 'PREVIEWED') {
    const preview = controller.getPreviewStore().get(payload.preview_id)
    if (!preview) {
      return batchErrorResponse(requestId, 'createSortingBatch', 'NOT_FOUND')
    }
    if (preview.ownerUserId !== actor.user_id) {
      return batchErrorResponse(requestId, 'createSortingBatch', 'FORBIDDEN')
    }
    if (
      preview.preview.selection_id !== payload.selection_id ||
      preview.preview.company_id !== selection.snapshot.company_id
    ) {
      return batchErrorResponse(requestId, 'createSortingBatch', 'INVALID_STATE')
    }
    if (
      gate === 'STALE_PREVIEW' ||
      controller
        .getPreviewStore()
        .isExpired(payload.preview_id, controller.getPreviewNow())
    ) {
      return batchErrorResponse(requestId, 'createSortingBatch', 'STALE_PREVIEW')
    }
  } else if (gate === 'SELECTION_CHANGED') {
    return batchErrorResponse(requestId, 'createSortingBatch', 'SELECTION_CHANGED')
  }

  const scenario = resolveCreateScenario(
    controller.getBatchScenario(),
    payload.execution_mode,
  )
  const basePage = getCannedBatchPage1(scenario)
  const identity: BatchIdentity = {
    batch_id: store.allocateBatchId(basePage.batch_id),
    company_id: selection.snapshot.company_id,
    selection_id: payload.selection_id,
    preview_id:
      payload.execution_mode === 'PREVIEWED' ? payload.preview_id : null,
    actor: cloneJson(actor),
    rule_set: cloneJson(basePage.rule_set),
    created_at: basePage.created_at,
  }
  const response = bindBatchPage(basePage, identity)
  const stored: StoredBatch = { identity, scenario, response }
  store.put(stored)
  store.recordOperation(actor.user_id, idempotencyKey, body.value, stored)
  return jsonResponse(response, requestId, 202)
}

/**
 * GET /sorting/batches/{batch_id}
 * → 200 Batch (literal страница текущей фазы) | 401 | 403 | 404 | 422 |
 * управляемая ошибка. 409 у чтения не объявлен.
 */
export const getSortingBatchHandler: MockHandler = ({
  controller,
  params,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parseBatchLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const stored = controller.getBatchStore().get(params.batch_id)
  if (!stored) {
    return notFoundResponse(requestId)
  }

  const forcedError = controller.consumeBatchError('getSortingBatch')
  if (forcedError) {
    return batchErrorResponse(requestId, 'getSortingBatch', forcedError)
  }

  const scenario = resolveReadScenario(
    controller.getBatchScenario(),
    controller.getBatchPhase(),
    stored,
  )
  const cursor = url.searchParams.get('cursor')
  const page = resolveCannedBatchPage(scenario, cursor)
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(bindBatchPage(page, stored.identity), requestId)
}

/**
 * GET /sorting/batches
 * → 200 BatchPage (BatchSummary компании, created_at DESC/batch_id DESC) |
 * 401 | 403 | 422 | управляемая ошибка.
 */
export const listSortingBatchesHandler: MockHandler = ({
  controller,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const companyId = url.searchParams.get('company_id')
  if (!companyId || companyId.trim().length === 0) {
    return missingCompanyIdResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parseBatchLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const forcedError = controller.consumeBatchError('listSortingBatches')
  if (forcedError) {
    return batchErrorResponse(requestId, 'listSortingBatches', forcedError)
  }

  const cursor = url.searchParams.get('cursor')
  const page = resolveBatchHistoryPage(
    controller.getBatchStore().listSummaries(companyId),
    { cursor, limit },
  )
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}
