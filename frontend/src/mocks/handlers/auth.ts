// Session handlers: login, getSession, logout.
//
// Mock не является защищённым auth backend: он сопоставляет тело входа с
// публичными synthetic-примерами `contracts/examples/auth/*.json` и выдаёт
// соответствующий пример `Session`. Реальные пароли, хеши и сессии не
// используются; пароль из примера — инертный placeholder, который никуда не
// логируется и не возвращается.

import { readJsonBody } from '../body'
import { getExample } from '../data'
import {
  csrfFailedResponse,
  jsonResponse,
  loginFailedResponse,
  noContentResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import type { LoginRequest, MockHandler, Session } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

// Id публичных примеров в порядке manifest.json. Сопоставление строится по
// данным примеров, а не по захардкоженным credentials.
const LOGIN_REQUEST_EXAMPLE_IDS = [
  'auth-login-request-worker-one',
  'auth-login-request-worker-two',
  'auth-login-request-admin',
] as const

const SESSION_EXAMPLE_IDS = [
  'auth-session-worker-one',
  'auth-session-worker-two',
  'auth-session-admin',
] as const

/** Находит session-пример по логину актора из login-примера. */
function findSessionForLogin(login: string): Session | null {
  for (const id of SESSION_EXAMPLE_IDS) {
    const session = getExample<Session>(id)
    if (session.actor.login === login) {
      return session
    }
  }
  return null
}

/**
 * Сопоставляет валидное тело с известными synthetic login-примерами. Полное
 * совпадение `login` и `password` примера — единственный способ успеха; иначе
 * login-failed. Значения не логируются.
 */
function matchLoginSession(body: LoginRequest): Session | null {
  for (const id of LOGIN_REQUEST_EXAMPLE_IDS) {
    const example = getExample<LoginRequest>(id)
    if (example.login === body.login && example.password === body.password) {
      return findSessionForLogin(example.login)
    }
  }
  return null
}

/** POST /auth/login → 200 Session | 401 LOGIN_FAILED | 422 VALIDATION_ERROR. */
export const loginHandler: MockHandler = async ({
  controller,
  request,
  requestId,
}) => {
  const body = await readJsonBody(request)
  if (!body.ok) {
    return validationErrorResponse(requestId, [
      {
        field: 'request',
        code: 'INVALID_BODY',
        message: 'Тело запроса должно быть корректным JSON.',
      },
    ])
  }

  const validation = validateSchema('LoginRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const session = matchLoginSession(body.value as LoginRequest)
  if (!session) {
    return loginFailedResponse(requestId)
  }

  controller.setSession(session)
  return jsonResponse(session, requestId)
}

/** GET /session → 200 Session | 401 UNAUTHENTICATED. */
export const sessionHandler: MockHandler = ({ controller, requestId }) => {
  const session = controller.getSession()
  if (!session) {
    return unauthenticatedResponse(requestId)
  }
  return jsonResponse(session, requestId)
}

/**
 * POST /auth/logout → 204 | 401 UNAUTHENTICATED | 403 CSRF_FAILED.
 *
 * Мутация объявлена с `#/components/parameters/XCSRFToken`: неверный или
 * отсутствующий токен даёт 403 и не завершает сессию.
 */
export const logoutHandler: MockHandler = ({
  controller,
  request,
  requestId,
}) => {
  const session = controller.getSession()
  if (!session) {
    return unauthenticatedResponse(requestId)
  }
  const csrfToken = request.headers.get('X-CSRF-Token')
  if (!csrfToken || csrfToken !== session.csrf_token) {
    return csrfFailedResponse(requestId)
  }
  controller.clearSession()
  return noContentResponse(requestId)
}
