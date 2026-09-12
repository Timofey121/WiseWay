// GET /companies/{company_id}/dictionaries, POST /companies/{company_id}/dictionaries,
// GET /dictionaries/{dictionary_id} и PUT /dictionaries/{dictionary_id}/draft
// (LT-07.1a).
//
// GET-операции требуют только активной mock-сессии; POST/PUT — сессию и
// корректный `X-CSRF-Token` (общий guard `requireSessionAndCsrf`). Тела
// валидируются по схемам OAS до любого успеха. Имя уникально внутри компании
// после trim+casefold (in-memory store), черновик заменяется атомарно с
// `draft_revision + 1`, stale-ревизия отклоняется без частичной записи. Ручная
// правка восстановленного черновика очищает `based_on_version_id` (LT-07.1c).
// Mock не выполняет matcher, publish/restore или файловые действия.

import { readJsonBody } from '../body'
import { declaredDictionaryErrorResponse } from '../dictionaries/errors'
import { isAllowedTarget } from '../dictionaries/targets'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  notFoundResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import type {
  CreateDictionaryRequest,
  DictionaryListResponse,
  MockHandler,
  ReplaceDictionaryDraftRequest,
} from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** GET /companies/{company_id}/dictionaries → 200 | 401 | управляемая ошибка. */
export const listDictionariesHandler: MockHandler = ({
  controller,
  params,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }
  const forcedError = controller.consumeDictionaryError('listDictionaries')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }
  const response: DictionaryListResponse = {
    items: controller.getDictionaryStore().list(params.company_id),
  }
  return jsonResponse(response, requestId)
}

/** GET /dictionaries/{dictionary_id} → 200 | 401 | 404 | управляемая ошибка. */
export const getDictionaryHandler: MockHandler = ({
  controller,
  params,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }
  const forcedError = controller.consumeDictionaryError('getDictionary')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }
  const dictionary = controller.getDictionaryStore().get(params.dictionary_id)
  if (!dictionary) {
    return notFoundResponse(requestId)
  }
  return jsonResponse(dictionary, requestId)
}

/**
 * POST /companies/{company_id}/dictionaries
 * → 201 Dictionary (пустой черновик revision=0) | 401 | 403 | 409
 * DICTIONARY_NAME_CONFLICT | 422 | управляемая ошибка.
 */
export const createDictionaryHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, params, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('CreateDictionaryRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeDictionaryError('createDictionary')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const payload = body.value as CreateDictionaryRequest
  const store = controller.getDictionaryStore()
  if (store.hasNameConflict(params.company_id, payload.name)) {
    return declaredDictionaryErrorResponse(
      requestId,
      'DICTIONARY_NAME_CONFLICT',
    )
  }
  const created = store.create(
    params.company_id,
    payload.name,
    payload.description,
    actor,
  )
  return jsonResponse(created, requestId, 201)
}

/**
 * PUT /dictionaries/{dictionary_id}/draft
 * → 200 Dictionary (revision+1) | 401 | 403 | 404 | 409
 * DRAFT_VERSION_CONFLICT/DICTIONARY_NAME_CONFLICT | 422 | управляемая ошибка.
 * Stale-ревизия и недопустимая цель отклоняют запись целиком, без частичного
 * сохранения.
 */
export const replaceDictionaryDraftHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, params, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema(
    'ReplaceDictionaryDraftRequest',
    body.value,
  )
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumeDictionaryError('replaceDictionaryDraft')
  if (forcedError) {
    return declaredDictionaryErrorResponse(requestId, forcedError)
  }

  const store = controller.getDictionaryStore()
  const current = store.get(params.dictionary_id)
  if (!current) {
    return notFoundResponse(requestId)
  }

  const payload = body.value as ReplaceDictionaryDraftRequest
  if (payload.expected_draft_revision !== current.draft.draft_revision) {
    return declaredDictionaryErrorResponse(requestId, 'DRAFT_VERSION_CONFLICT')
  }
  if (
    store.hasNameConflict(
      current.company_id,
      payload.name,
      current.dictionary_id,
    )
  ) {
    return declaredDictionaryErrorResponse(
      requestId,
      'DICTIONARY_NAME_CONFLICT',
    )
  }

  const ruleIds = new Set<string>()
  for (const rule of payload.rules) {
    if (ruleIds.has(rule.rule_id)) {
      return validationErrorResponse(requestId, [
        {
          field: 'rules',
          code: 'DUPLICATE_RULE_ID',
          message: 'Идентификаторы правил должны быть уникальны.',
        },
      ])
    }
    ruleIds.add(rule.rule_id)
  }
  for (const rule of payload.rules) {
    if (
      !isAllowedTarget(
        current.company_id,
        rule.target.root_id,
        rule.target.relative_directory,
      )
    ) {
      return declaredDictionaryErrorResponse(requestId, 'INVALID_TARGET')
    }
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }
  // Ручная правка восстановленного черновика очищает происхождение restore
  // (API §6): `based_on_version_id` снимается, черновик становится обычным
  // кандидатом.
  const publishingStore = controller.getPublishingStore()
  const restoredDraft = publishingStore.isRestoredDraft(params.dictionary_id)
  const saved = store.replaceDraft(
    params.dictionary_id,
    {
      name: payload.name,
      description: payload.description,
      rules: payload.rules,
    },
    actor,
    { clearBasedOnVersion: restoredDraft },
  )
  if (restoredDraft) {
    publishingStore.clearRestoredDraft(params.dictionary_id)
  }
  return jsonResponse(saved, requestId)
}
