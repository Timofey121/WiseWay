// GET /app-config → 200 AppConfig (default N=100 / профиль N=10).

import { getExample } from '../data'
import { jsonResponse, unauthenticatedResponse } from '../responses'
import type { AppConfig, MockHandler } from '../types'
import type { ConfigProfile } from '../controller'

const EXAMPLE_ID_BY_PROFILE: Record<ConfigProfile, string> = {
  n100: 'config-app-config-n100',
  n10: 'config-app-config-n10',
}

/** GET /app-config → 200 AppConfig | 401 UNAUTHENTICATED. */
export const appConfigHandler: MockHandler = ({ controller, requestId }) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }
  const config = getExample<AppConfig>(
    EXAMPLE_ID_BY_PROFILE[controller.getConfigProfile()],
  )
  return jsonResponse(config, requestId)
}
