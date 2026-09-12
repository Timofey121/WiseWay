// POST /dictionaries/{dictionary_id}/simulate (createDictionarySimulation) и
// GET /simulations/{simulation_id} (getSimulation) — LT-07.1b.
//
// Операции отдают literal canned-сценарии из
// `contracts/examples/simulations/*.json`: READY full (две страницы), empty
// (`EMPTY_READY_SET`), conflict, same-target и no-scenario. Mock не выполняет
// matcher, ranking, расчёт плана или файловые действия — он выбирает заранее
// заданный сценарий контроллера.
//
// `createDictionarySimulation` — объявленная мутация (`csrf: true`): требует
// активную mock-сессию и корректный `X-CSRF-Token`, валидирует
// `CreateSimulationRequest`, проверяет существование справочника (404) и
// `expected_draft_revision` против ТЕКУЩЕЙ ревизии `DictionaryStore` (той же,
// что возвращает `GET /dictionary`); несовпадение → 409
// `DRAFT_VERSION_CONFLICT`. Успех — 201 `Simulation` первой страницы выбранного
// сценария с `draft_revision`, равной провалидированной текущей ревизии; plan
// rows/counts/rule_set/base_rule_set остаются literal из примера.
//
// `getSimulation` — чтение: требует только активную mock-сессию, поддерживает
// finite `cursor`/`limit` и неизвестный id → 404. Операция объявляет только
// 200/401/403/404/422/429/500/503: 409 здесь не возвращается. Сохранённый
// результат отдаётся независимо от последующих изменений черновика; staleness —
// предмет publish (LT-07.1c).

import { readJsonBody } from '../body'
import { declaredSimulationErrorResponse } from '../simulations/errors'
import {
  parseSimulationLimit,
  resolveSimulationPage,
  type SimulationScenario,
} from '../simulations/store'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  notFoundResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import type { CreateSimulationRequest, MockHandler } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы. */
const CURSOR_ERROR = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
} as const

/**
 * POST /dictionaries/{dictionary_id}/simulate
 * → 201 Simulation | 401 | 403 | 404 | 409 (устаревшая ревизия) | 422 |
 * управляемая ошибка. Возвращает первую объявленную страницу сценария.
 */
export const createDictionarySimulationHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, params, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('CreateSimulationRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeSimulationError(
    'createDictionarySimulation',
  )
  if (forcedError) {
    return declaredSimulationErrorResponse(requestId, forcedError)
  }

  const dictionary = controller.getDictionaryStore().get(params.dictionary_id)
  if (!dictionary) {
    return notFoundResponse(requestId)
  }

  const payload = body.value as CreateSimulationRequest
  const currentRevision = dictionary.draft.draft_revision
  if (payload.expected_draft_revision !== currentRevision) {
    // OAS `createDictionarySimulation` 409 = `DraftVersionConflict`; literal-фикстура
    // `simulate-stale-draft` ожидает именно DRAFT_VERSION_CONFLICT.
    return declaredSimulationErrorResponse(requestId, 'DRAFT_VERSION_CONFLICT')
  }

  const scenario: SimulationScenario = controller.getSimulationScenario()
  const store = controller.getSimulationStore()
  const stored = store.getScenario(scenario)
  // Без курсора страница строится всегда; null здесь недостижим.
  const page = resolveSimulationPage(stored, { cursor: null, limit: null })
  if (!page) {
    return notFoundResponse(requestId)
  }
  store.markCreated(stored.base.simulation_id, currentRevision)
  return jsonResponse(
    { ...page, draft_revision: currentRevision },
    requestId,
    201,
  )
}

/**
 * GET /simulations/{simulation_id}
 * → 200 Simulation (очередная страница) | 401 | 404 | 422 (limit/cursor) |
 * управляемая ошибка. 409 не объявлен и не возвращается.
 */
export const getSimulationHandler: MockHandler = ({
  controller,
  params,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parseSimulationLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const cursor = url.searchParams.get('cursor')
  const stored = controller.getSimulationStore().get(params.simulation_id)
  if (!stored) {
    return notFoundResponse(requestId)
  }

  const forcedError = controller.consumeSimulationError('getSimulation')
  if (forcedError) {
    return declaredSimulationErrorResponse(requestId, forcedError)
  }

  const page = resolveSimulationPage(stored, { cursor, limit })
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}
