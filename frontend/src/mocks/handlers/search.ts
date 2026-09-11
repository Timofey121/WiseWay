// POST /search и POST /search/facet → literal golden-ответ | объявленная ошибка.
//
// LT-06.2a-ii: HTTP-слой только маршрутизирует и валидирует. Тело проверяется по
// схемам OAS (`SearchRequest`/`FacetRequest`); literal-ответ формирует
// foundation `resolveSearchScenario`/`resolveFacetScenario`. Handler не
// выполняет matcher, ranking, пересортировку или парсинг путей и ничего не
// изменяет: обе операции — чтение (`csrf: false`, `idempotencyKey: false`).
//
// LT-06.2b: до нормального lookup handler применяет управляемую задержку
// своего scope (`search`/`facet` независимы) и объявленную ошибку операции из
// контроллера. Ошибка возвращается ровно контрактным примером
// (`SearchErrorCode`), без выдуманных кодов и без правдоподобного успеха.
//
// `request_state_id` всегда эхо исходной отправки; freshness-профиль берётся из
// контроллера (CURRENT по умолчанию). Ненайденный golden-сценарий даёт
// объявленную контрактом 400 `INVALID_QUERY`, а не правдоподобный успех.
//
// Требуется активная mock-сессия: без неё оба метода отвечают 401
// `UNAUTHENTICATED` (как и остальные операции без `security: []`).

import { readJsonBody } from '../body'
import {
  invalidQueryResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import { declaredSearchErrorResponse } from '../search/errors'
import {
  resolveFacetScenario,
  resolveSearchScenario,
} from '../search/expectations'
import type { FacetRequest, MockHandler, SearchRequest } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная 422 для пустого/битого JSON-тела без эха значений. */
function invalidBodyResponse(requestId: string): Response {
  return validationErrorResponse(requestId, [
    {
      field: 'request',
      code: 'INVALID_BODY',
      message: 'Тело запроса должно быть корректным JSON.',
    },
  ])
}

/**
 * POST /search → 200 SearchResponse | 400 INVALID_QUERY | 401 | 422.
 *
 * `schema_set_version` участвует только в schema-валидации: literal golden
 * сценарий разрешается по условиям запроса, а версия схемы/поколение берутся
 * из корня foundation.
 */
export const searchHandler: MockHandler = async ({
  controller,
  request,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  await controller.waitForScope('search')

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }

  const validation = validateSchema('SearchRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeError('searchFiles')
  if (forcedError) {
    return declaredSearchErrorResponse(requestId, forcedError)
  }

  const searchRequest = body.value as SearchRequest
  const response = resolveSearchScenario(
    {
      request_state_id: searchRequest.request_state_id,
      root_id: searchRequest.root_id,
      selected_marker_ids: searchRequest.selected_marker_ids,
      query_text: searchRequest.query_text,
      sort: {
        field: searchRequest.sort.field,
        direction: searchRequest.sort.direction,
      },
      facet_prefix: searchRequest.facet_prefix,
    },
    { freshnessProfile: controller.getSearchFreshnessProfile() },
  )
  if (!response) {
    return invalidQueryResponse(requestId)
  }
  return jsonResponse(response, requestId)
}

/** POST /search/facet → 200 FacetResponse | 400 INVALID_QUERY | 401 | 422. */
export const searchFacetHandler: MockHandler = async ({
  controller,
  request,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  await controller.waitForScope('facet')

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }

  const validation = validateSchema('FacetRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeError('getSearchFacet')
  if (forcedError) {
    return declaredSearchErrorResponse(requestId, forcedError)
  }

  const facetRequest = body.value as FacetRequest
  const response = resolveFacetScenario({
    request_state_id: facetRequest.request_state_id,
    root_id: facetRequest.root_id,
    selected_marker_ids: facetRequest.selected_marker_ids,
    query_text: facetRequest.query_text,
    facet_prefix: facetRequest.facet_prefix,
  })
  if (!response) {
    return invalidQueryResponse(requestId)
  }
  return jsonResponse(response, requestId)
}
