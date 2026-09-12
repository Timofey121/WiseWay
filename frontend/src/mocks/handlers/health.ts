// GET /health → 200 {status: 'ok'} (без сессии, OAS security: []).

import { jsonResponse } from '../responses'
import type { MockHandler } from '../types'

export const healthHandler: MockHandler = ({ requestId }) =>
  jsonResponse({ status: 'ok' }, requestId)
