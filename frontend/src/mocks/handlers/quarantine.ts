// GET /quarantine (listQuarantineItems) и
// POST /quarantine/{quarantine_id}/return (returnQuarantineItem) — LT-07.3a.
//
// Операции отдают literal canned-данные из
// `contracts/examples/quarantine/*.json`. Mock не выполняет возврат файла,
// recovery, перемещение, автосортировку и не ведёт журнал: он проверяет вход,
// воспроизводит объявленные gates/конфликты и выбирает заранее заданное
// состояние записи контроллера.
//
// `listQuarantineItems` — чтение: требует активную mock-сессию,
// `company_id` обязателен, `cursor` — `quarantine-offset-<n>`, `limit` 1..100.
// Список company-scoped и содержит только подтверждённые записи карантина;
// неизвестная компания даёт пустую страницу. Невалидный `cursor`/`limit` → 422.
//
// `returnQuarantineItem` — объявленная мутация (`csrf: true`,
// `idempotencyKey: true`): требует сессию, корректный `X-CSRF-Token` и
// непустой `Idempotency-Key`, валидирует `QuarantineReturnRequest`
// (`expected_revision`, `comment` 1..500). Gates объявлены контрактом:
//  * неизвестный `quarantine_id` → 404 `NOT_FOUND`;
//  * уже возвращённая запись с новым ключом → 409 `INVALID_STATE`;
//  * неоднозначный возврат → 409 `RECOVERY_REQUIRED` с зарегистрированным
//    `error.operation_id` (без выдуманного успешного размещения);
//  * устаревшая `expected_revision` → 409 `QUARANTINE_VERSION_CONFLICT`;
//  * занятый исходный путь → 409 `ORIGINAL_PATH_OCCUPIED` без мутаций;
//  * comment вне 1..500 → 422 `VALIDATION_ERROR`.
// Успех — 200 literal `QuarantineReturnResponse`
// (`item.status=WAITING_READY`, `selectable=false`, без active attempt), без
// batch POST и автосортировки.
//
// Идемпотентность scoped по actor+ключу: повтор того же ключа/тела возвращает
// прежний исход **до** staleness/state-проверок (API §2, потерянный ответ);
// другое тело с тем же ключом → 409 `IDEMPOTENCY_KEY_REUSED`; тот же ключ у
// другого пользователя — отдельный scope.

import { readJsonBody } from '../body'
import { cloneJson } from '../data'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import { quarantineErrorResponse } from '../quarantine/errors'
import {
  parseQuarantineLimit,
  resolveQuarantinePage,
  type QuarantineOperationOutcome,
} from '../quarantine/store'
import type {
  QuarantineReturnRequest,
  FieldError,
  MockHandler,
} from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы. */
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

/** Строит ответ на зарегистрированный исход операции (replay). */
function replayOutcome(
  requestId: string,
  outcome: QuarantineOperationOutcome,
): Response {
  if (outcome.kind === 'returned') {
    return jsonResponse(cloneJson(outcome.response), requestId)
  }
  return quarantineErrorResponse(
    requestId,
    'returnQuarantineItem',
    'RECOVERY_REQUIRED',
    { operationId: outcome.operationId },
  )
}

/**
 * GET /quarantine
 * → 200 `QuarantinePage` (literal подтверждённых записей компании) | 401 |
 * 403 | 422 | управляемая ошибка. Только подтверждённый карантин; неизвестная
 * компания — пустая страница.
 */
export const listQuarantineItemsHandler: MockHandler = ({
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
  const limit = limitRaw === null ? null : parseQuarantineLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [LIMIT_ERROR])
  }

  const managed = controller.consumeQuarantineError('listQuarantineItems')
  if (managed) {
    return quarantineErrorResponse(requestId, 'listQuarantineItems', managed)
  }

  const cursor = url.searchParams.get('cursor')
  const items = controller.getQuarantineStore().listByCompany(companyId)
  const page = resolveQuarantinePage(items, { cursor, limit })
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}

/**
 * POST /quarantine/{quarantine_id}/return
 * → 200 `QuarantineReturnResponse` (literal) | 401 | 403 | 404 | 409 | 422 |
 * управляемая ошибка. Идемпотентный replay идёт до staleness/state-проверок.
 */
export const returnQuarantineItemHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, request, requestId, params } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('QuarantineReturnRequest', body.value)
  if (!validation.valid) {
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'VALIDATION_ERROR',
      { fieldErrors: toFieldErrors(validation.errors) },
    )
  }

  const idempotencyKey = request.headers.get('Idempotency-Key')
  if (!idempotencyKey || idempotencyKey.trim().length === 0) {
    return missingIdempotencyKeyResponse(requestId)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const payload = body.value as QuarantineReturnRequest
  const store = controller.getQuarantineStore()

  // Ключ проверяется до staleness/state-проверок: потерянный ответ принятого
  // возврата должен воспроизводиться и после изменения ревизии/состояния.
  const lookup = store.resolveOperation(actor.user_id, idempotencyKey, payload)
  if (lookup) {
    if (lookup.kind === 'reused') {
      return quarantineErrorResponse(
        requestId,
        'returnQuarantineItem',
        'IDEMPOTENCY_KEY_REUSED',
      )
    }
    return replayOutcome(requestId, lookup.outcome)
  }

  const managed = controller.consumeQuarantineError('returnQuarantineItem')
  if (managed) {
    return quarantineErrorResponse(requestId, 'returnQuarantineItem', managed)
  }

  const record = store.getRecord(params.quarantine_id)
  if (!record) {
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'NOT_FOUND',
    )
  }
  if (record.returned) {
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'INVALID_STATE',
    )
  }

  const recoveryOperationId = record.item.recovery_operation_id
  if (!record.item.can_return || recoveryOperationId !== null) {
    if (recoveryOperationId === null) {
      // can_return=false без зарегистрированной операции не возвращается:
      // безопасный отказ вместо выдуманного recovery.
      return quarantineErrorResponse(
        requestId,
        'returnQuarantineItem',
        'INVALID_STATE',
      )
    }
    store.recordOperation(actor.user_id, idempotencyKey, payload, {
      kind: 'recovery',
      operationId: recoveryOperationId,
    })
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'RECOVERY_REQUIRED',
      { operationId: recoveryOperationId },
    )
  }

  if (payload.expected_revision !== record.item.revision) {
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'QUARANTINE_VERSION_CONFLICT',
    )
  }

  if (controller.getQuarantineGate() === 'ORIGINAL_PATH_OCCUPIED') {
    return quarantineErrorResponse(
      requestId,
      'returnQuarantineItem',
      'ORIGINAL_PATH_OCCUPIED',
    )
  }

  const response = store.returnItem()
  store.recordOperation(actor.user_id, idempotencyKey, payload, {
    kind: 'returned',
    response: cloneJson(response),
  })
  return jsonResponse(cloneJson(response), requestId)
}
