// GET /roots и GET /companies → 200 | 401 UNAUTHENTICATED.

import { getExample } from '../data'
import { jsonResponse, unauthenticatedResponse } from '../responses'
import type { CompaniesResponse, MockHandler, RootsResponse } from '../types'

/** GET /roots → 200 RootsResponse | 401 UNAUTHENTICATED. */
export const rootsHandler: MockHandler = ({ controller, requestId }) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }
  const id = controller.isRootsEmpty() ? 'roots-empty' : 'roots-two'
  return jsonResponse(getExample<RootsResponse>(id), requestId)
}

/** GET /companies → 200 CompaniesResponse | 401 UNAUTHENTICATED. */
export const companiesHandler: MockHandler = ({ controller, requestId }) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }
  const id = controller.isCompaniesEmpty()
    ? 'companies-empty'
    : 'companies-atlas-nova'
  return jsonResponse(getExample<CompaniesResponse>(id), requestId)
}
