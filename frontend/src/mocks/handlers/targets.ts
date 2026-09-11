// GET /companies/{company_id}/target-directories и
// POST /companies/{company_id}/target-directories/resolve (LT-07.1a).
//
// Обе операции — чтение (`csrf: false`): они не несут `X-CSRF-Token` и требуют
// только активной mock-сессии. `listTargetDirectories` отдаёт finite-страницу
// настроенного allowlist компании (`prefix`/`cursor`/`limit`); resolver ищет
// `display_path` в том же allowlist и никогда не создаёт каталоги. Файловый
// доступ, matcher и вычисление целей отсутствуют.

import { readJsonBody } from '../body'
import { declaredDictionaryErrorResponse } from '../dictionaries/errors'
import {
  listTargetsPage,
  parseTargetCursor,
  parseTargetLimit,
  resolveTargetDisplayPath,
} from '../dictionaries/targets'
import {
  invalidBodyResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import type { MockHandler, ResolveTargetRequest } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/**
 * GET /companies/{company_id}/target-directories
 * → 200 PageTargetDirectory | 401 | 422 (limit/cursor) | управляемая ошибка.
 */
export const listTargetDirectoriesHandler: MockHandler = ({
  controller,
  params,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? 100 : parseTargetLimit(limitRaw)
  if (limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const cursor = url.searchParams.get('cursor')
  if (cursor !== null && parseTargetCursor(cursor) === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'cursor',
        code: 'CURSOR',
        message: 'Курсор страницы недействителен.',
      },
    ])
  }

  const forcedError = controller.consumeDictionaryError('listTargetDirectories')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }

  const page = listTargetsPage({
    companyId: params.company_id,
    prefix: url.searchParams.get('prefix') ?? '',
    cursor,
    limit,
  })
  return jsonResponse(page, requestId)
}

/**
 * POST /companies/{company_id}/target-directories/resolve
 * → 200 TargetDirectory | 401 | 422 INVALID_TARGET/PATH_OUTSIDE_ROOT/
 * VALIDATION_ERROR | управляемая ошибка. Resolver не создаёт каталоги.
 */
export const resolveTargetDirectoryHandler: MockHandler = async ({
  controller,
  params,
  request,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('ResolveTargetRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeDictionaryError('resolveTargetDirectory')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }

  const payload = body.value as ResolveTargetRequest
  const result = resolveTargetDisplayPath(params.company_id, payload.display_path)
  if (result.ok) {
    return jsonResponse(result.target, requestId)
  }
  return declaredDictionaryErrorResponse(requestId, result.code)
}
