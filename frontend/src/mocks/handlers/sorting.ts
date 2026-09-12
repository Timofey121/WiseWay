// POST /sorting/queue/query (querySortingQueue) и
// POST /sorting/selections (createSortingSelection) — LT-07.2a.
//
// Операции отдают literal canned-сценарии из
// `contracts/examples/sorting/*.json`: очередь компании (0/120/1001 готовых,
// все активные 0/120, явный MISSING, literal query_text) и неизменяемый снимок
// выбора (EXPLICIT/ALL_MATCHING). Mock не выполняет matcher, readiness-детектор,
// подсчёт membership/counters и не реализует claim/snapshot-алгоритм: он
// проверяет входные поля и выбирает заранее заданный сценарий контроллера.
//
// `querySortingQueue` — чтение (`csrf: false`): требует активную mock-сессию,
// валидирует `QueueQueryRequest` (company_id, filters, cursor, limit 1..100 по
// схеме OAS) и отдаёт canned `QueueResponse` выбранного queue-сценария.
// Объявлена только первая страница, поэтому непустой `cursor` → 422
// `VALIDATION_ERROR`: mock не выдумывает вторую страницу.
//
// `createSortingSelection` — объявленная мутация (`csrf: true`): требует
// активную mock-сессию и корректный `X-CSRF-Token`, валидирует
// `SelectionRequest` (oneOf EXPLICIT/ALL_MATCHING). EXPLICIT отдаёт canned
// snapshot по числу элементов. ALL_MATCHING сверяет `expected_eligible_count`
// с canned eligible_count текущего queue-сценария: 0 → 422 `EMPTY_SELECTION`,
// > 1000 → 422 `BATCH_LIMIT_EXCEEDED` без усечения, расхождение → 409
// `SELECTION_CHANGED`. Созданный снимок сохраняется в `SelectionStore`, поэтому
// поздние поступления не меняют его. Owner/expiry/unknown снимка объявлены для
// preview/batch (не для create) и воспроизводятся резолвером store.

import { readJsonBody } from '../body'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import {
  declaredSortingErrorResponse,
} from '../sorting/errors'
import {
  getCannedQueueResponse,
  matchesQueueScenarioFilters,
  resolveCannedQueuePage,
} from '../sorting/queue'
import { resolveSelectionCreation } from '../sorting/selection'
import type { MockHandler, QueueQueryRequest, SelectionRequest } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора очереди. */
const CURSOR_ERROR = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
} as const

/**
 * POST /sorting/queue/query
 * → 200 QueueResponse (literal canned) | 401 | 403 | 422 | управляемая ошибка.
 * `cursor`/`limit` валидируются схемой; объявленной второй страницы нет, поэтому
 * непустой `cursor` отклоняется без выдуманного успеха.
 */
export const querySortingQueueHandler: MockHandler = async (context) => {
  if (!context.controller.isAuthenticated()) {
    return unauthenticatedResponse(context.requestId)
  }
  const { controller, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('QueueQueryRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeSortingError('querySortingQueue')
  if (forcedError) {
    return declaredSortingErrorResponse(requestId, forcedError)
  }

  const payload = body.value as QueueQueryRequest
  const scenario = controller.getQueueScenario()
  if (!matchesQueueScenarioFilters(scenario, payload.filters)) {
    return validationErrorResponse(requestId, [
      {
        field: 'filters',
        code: 'FILTERS',
        message: 'Для выбранного фильтра нет объявленного сценария очереди.',
      },
    ])
  }
  const canned = getCannedQueueResponse(scenario)
  const page = resolveCannedQueuePage(canned, payload.cursor)
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}

/**
 * POST /sorting/selections
 * → 201 SelectionSnapshot (literal canned) | 401 | 403 | 409 SELECTION_CHANGED |
 * 422 VALIDATION_ERROR/EMPTY_SELECTION/BATCH_LIMIT_EXCEEDED | управляемая
 * ошибка. Созданный снимок сохраняется и не меняется поздними поступлениями.
 */
export const createSortingSelectionHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('SelectionRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeSortingError('createSortingSelection')
  if (forcedError) {
    return declaredSortingErrorResponse(requestId, forcedError)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const payload = body.value as SelectionRequest
  const scenario = controller.getQueueScenario()
  if (
    payload.mode === 'ALL_MATCHING' &&
    !matchesQueueScenarioFilters(scenario, payload.filters)
  ) {
    return validationErrorResponse(requestId, [
      {
        field: 'filters',
        code: 'FILTERS',
        message: 'Для выбранного фильтра нет объявленного сценария очереди.',
      },
    ])
  }

  const creation = resolveSelectionCreation(payload, {
    currentQueue: getCannedQueueResponse(scenario),
    eligibleCountOverride: controller.getEligibleCountOverride(),
    ownerUserId: actor.user_id,
  })

  if (creation.kind === 'empty') {
    return declaredSortingErrorResponse(requestId, 'EMPTY_SELECTION')
  }
  if (creation.kind === 'limit') {
    return declaredSortingErrorResponse(requestId, 'BATCH_LIMIT_EXCEEDED')
  }
  if (creation.kind === 'changed') {
    return declaredSortingErrorResponse(requestId, 'SELECTION_CHANGED')
  }

  controller.getSelectionStore().put(creation.selection)
  return jsonResponse(creation.selection.snapshot, requestId, 201)
}
