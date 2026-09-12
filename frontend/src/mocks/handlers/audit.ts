// POST /audit/query (queryAuditEvents), GET /audit/updates (getAuditUpdates) и
// GET /audit/actors (listAuditActors) — LT-07.3b.
//
// Операции отдают literal canned-данные из `contracts/examples/audit/*.json`.
// Mock НЕ ведёт журнал, не реализует запись, immutability, серверный
// фильтр-алгоритм, cursor-store или actor-directory: он проверяет вход,
// воспроизводит объявленные управляемые ошибки и делает lookup заранее
// заданной страницы по фильтрам/сценарию и роли сессии.
//
// `queryAuditEvents` — чтение (csrf не объявлен): требует активную mock-сессию,
// валидирует `AuditQueryRequest` (nullable company_id/actor_id/action/result,
// `query_text`, `cursor`, `limit` 1..100) и объявленный порядок интервала
// `[from,to)`. Невалидный интервал → 422 `VALIDATION_ERROR`
// (`error-audit-validation`, поле `from`). Чувствительные фильтры идут в теле
// POST и не попадают в URL. Роль из сессии: WORKER видит BUSINESS, ADMIN —
// BUSINESS+SYSTEM (canned-переключение).
//
// `getAuditUpdates` — чтение: `after_event_id` необязателен; отсутствие
// параметра означает первичный пустой журнал без нижней границы. Ответ —
// `{has_new_events}` без текстов фильтров; `after_event_id` валидируется по
// схеме `Id` OAS (1..96 `[A-Za-z0-9-]`), пустой/недопустимый → 422.
//
// `listAuditActors` — чтение: `prefix` (регистронезависимо), `cursor`
// (`audit-actors-offset-<n>`) и `limit` 1..100; literal `ActorPage` включает
// заблокированного автора с доступными событиями. Невалидный курсор/limit → 422.

import { readJsonBody } from '../body'
import {
  invalidBodyResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import { auditErrorResponse } from '../audit/errors'
import { isValidAuditInterval, parseAuditLimit } from '../audit/store'
import type {
  AuditQueryRequest,
  FieldError,
  MockHandler,
  MockRequestContext,
} from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы авторов. */
const CURSOR_ERROR: FieldError = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
}

/** Безопасная ошибка недействительного размера страницы. */
const LIMIT_ERROR: FieldError = {
  field: 'limit',
  code: 'LIMIT',
  message: 'Размер страницы должен быть от 1 до 100.',
}

/** Схема `Id` публичного OAS: 1..96 символов `[A-Za-z0-9-]`. */
const ID_PATTERN = /^[A-Za-z0-9-]{1,96}$/

/** Роль читателя журнала из активной mock-сессии. */
function sessionRole(context: MockRequestContext): 'WORKER' | 'ADMIN' {
  return context.controller.getSession()?.actor.role ?? 'WORKER'
}

/**
 * POST /audit/query
 * → 200 `AuditQueryResponse` (literal canned-страница) | 401 | 403 | 422 |
 * управляемая ошибка. Тело валидируется по `AuditQueryRequest`, порядок
 * интервала проверяется до выбора страницы.
 */
export const queryAuditEventsHandler: MockHandler = async (context) => {
  const { controller, request, requestId } = context
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('AuditQueryRequest', body.value)
  if (!validation.valid) {
    return auditErrorResponse(requestId, 'queryAuditEvents', 'VALIDATION_ERROR', {
      fieldErrors: toFieldErrors(validation.errors),
    })
  }

  const payload = body.value as AuditQueryRequest
  if (!isValidAuditInterval(payload.from, payload.to)) {
    return auditErrorResponse(requestId, 'queryAuditEvents', 'VALIDATION_ERROR', {
      fieldErrors: [
        {
          field: 'from',
          code: 'ORDER',
          message: 'Начало интервала должно быть раньше конца.',
        },
      ],
    })
  }

  const managed = controller.consumeAuditError('queryAuditEvents')
  if (managed) {
    return auditErrorResponse(requestId, 'queryAuditEvents', managed)
  }

  const page = controller
    .getAuditStore()
    .resolveQuery(payload, sessionRole(context))
  return jsonResponse(page, requestId)
}

/**
 * GET /audit/updates
 * → 200 `AuditUpdatesResponse` | 401 | 403 | 422 | управляемая ошибка.
 * Отсутствие `after_event_id` — первичный пустой журнал без нижней границы;
 * пустое значение параметра → 422. Тексты фильтров в URL не передаются.
 */
export const getAuditUpdatesHandler: MockHandler = (context) => {
  const { controller, requestId, url } = context
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const afterRaw = url.searchParams.get('after_event_id')
  if (afterRaw !== null && !ID_PATTERN.test(afterRaw)) {
    return auditErrorResponse(requestId, 'getAuditUpdates', 'VALIDATION_ERROR', {
      fieldErrors: [
        {
          field: 'after_event_id',
          code: 'INVALID',
          message: 'Недопустимый идентификатор события.',
        },
      ],
    })
  }

  const managed = controller.consumeAuditError('getAuditUpdates')
  if (managed) {
    return auditErrorResponse(requestId, 'getAuditUpdates', managed)
  }

  const response = controller
    .getAuditStore()
    .resolveUpdates(afterRaw, sessionRole(context))
  return jsonResponse(response, requestId)
}

/**
 * GET /audit/actors
 * → 200 `ActorPage` (literal авторы, включая заблокированного) | 401 | 403 |
 * 422 | управляемая ошибка. `prefix` регистронезависим; `limit` 1..100;
 * неизвестный `cursor` → 422.
 */
export const listAuditActorsHandler: MockHandler = ({
  controller,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parseAuditLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [LIMIT_ERROR])
  }

  const managed = controller.consumeAuditError('listAuditActors')
  if (managed) {
    return auditErrorResponse(requestId, 'listAuditActors', managed)
  }

  const prefix = url.searchParams.get('prefix') ?? ''
  const cursor = url.searchParams.get('cursor')
  const page = controller.getAuditStore().resolveActors({
    prefix,
    cursor,
    limit,
  })
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}
