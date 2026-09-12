// Общие guard-хелперы mock-handlers.
//
// Мутации, объявленные в OAS с `#/components/parameters/XCSRFToken`, требуют
// активной mock-сессии и корректного `X-CSRF-Token`; отсутствие/неверный токен
// даёт 403 CSRF_FAILED, отсутствие сессии — 401 UNAUTHENTICATED. Guard общий для
// всех таких операций (logout, createDictionary, replaceDictionaryDraft), чтобы
// поведение было единым. Это воспроизведение контрактного поведения, а не
// доказательство безопасности реального сервера.

import { csrfFailedResponse, unauthenticatedResponse } from './responses'
import type { MockRequestContext } from './types'

/**
 * Проверяет сессию и CSRF-токен для mutation-операции. Возвращает готовый
 * `Response` (401/403) при отказе или `null`, если запрос можно продолжить.
 */
export function requireSessionAndCsrf(
  context: MockRequestContext,
): Response | null {
  const session = context.controller.getSession()
  if (!session) {
    return unauthenticatedResponse(context.requestId)
  }
  const csrfToken = context.request.headers.get('X-CSRF-Token')
  if (!csrfToken || csrfToken !== session.csrf_token) {
    return csrfFailedResponse(context.requestId)
  }
  return null
}
