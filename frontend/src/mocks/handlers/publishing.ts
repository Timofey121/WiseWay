// GET /dictionaries/{dictionary_id}/versions,
// GET /dictionaries/{dictionary_id}/versions/{version_id},
// POST /dictionaries/{dictionary_id}/restore-draft и
// POST /dictionaries/{dictionary_id}/publish (LT-07.1c).
//
// Операции отдают literal canned-примеры из
// `contracts/examples/dictionaries/*.json`: список/чтение версий, результат
// restore и результат publish v2/v3. Mock не выполняет matcher, priority
// selection, RuleSet-вычисление, revision bump или файловые действия — он
// проверяет входные поля и объявленные canned-сценарии.
//
// `publishDictionary` — объявленная мутация (`csrf: true`,
// `idempotencyKey: true`): требует активную mock-сессию, корректный
// `X-CSRF-Token` и непустой `Idempotency-Key`, валидирует
// `PublishDictionaryRequest` (comment 1..500). Gates воспроизводимы по
// canned-состоянию:
//  * неизвестный dictionary/simulation → 404;
//  * `expected_draft_revision` ≠ текущей ревизии `DictionaryStore` → 409
//    `DRAFT_VERSION_CONFLICT`;
//  * simulation создана поверх другой ревизии или истёк её `expires_at` → 409
//    `STALE_SIMULATION`;
//  * `counts.rule_conflicts > 0` → 409 `RULE_CONFLICT`;
//  * `counts.no_scenario > 0` без `acknowledge_no_scenario` → 409
//    `NO_SCENARIO_ACK_REQUIRED`.
//
// Идемпотентность: ключ scoped по actor + dictionary. Повтор того же
// ключа/тела возвращает прежний результат **до** проверки staleness (API §2);
// другое тело с тем же ключом → 409 `IDEMPOTENCY_KEY_REUSED`. Успех обновляет
// `DictionaryStore`, историю версий и literal RuleSet; сортировка/файловые
// действия не запускаются.
//
// `restoreDictionaryDraft` — мутация (`csrf: true`): валидирует
// `{version_id, expected_draft_revision}`, неизвестный dictionary/version →
// 404, stale-ревизия → 409 `DRAFT_VERSION_CONFLICT`. Успех переносит правила
// версии в черновик (`revision+1`, `based_on_version_id` установлен) и
// помечает черновик восстановленным; последующая ручная правка очищает
// provenance (`handlers/dictionaries.ts`).
//
// `listDictionaryVersions`/`getDictionaryVersion` — чтение: требуют только
// активную mock-сессию, неизвестный dictionary/version → 404, невалидный
// `cursor`/`limit` → 422. 409 у чтения не объявлен и не возвращается.

import { readJsonBody } from '../body'
import { cloneJson } from '../data'
import { MOCK_DICTIONARY_UPDATED_AT } from '../dictionaries/store'
import { requireSessionAndCsrf } from '../guards'
import {
  declaredPublishingErrorResponse,
} from '../publishing/errors'
import {
  parseVersionsLimit,
  resolveVersionsPage,
  type PublishingStore,
} from '../publishing/store'
import {
  invalidBodyResponse,
  jsonResponse,
  notFoundResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import type {
  Actor,
  Dictionary,
  DictionaryVersion,
  MockHandler,
  PublishDictionaryRequest,
  RestoreDictionaryDraftRequest,
} from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы версий. */
const CURSOR_ERROR = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
} as const

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

/**
 * Собирает восстановленный черновик из выбранной версии: name/description/
 * rules версии → draft, `based_on_version_id=version_id`, `draft_revision+1`.
 * `active_version_id`/`versions_count` берутся из текущего состояния
 * (`...current`) и не меняются: restore — не публикация (API §6).
 */
function buildRestoredDictionary(
  current: Dictionary,
  version: DictionaryVersion,
  actor: Actor,
): Dictionary {
  return {
    ...cloneJson(current),
    name: version.name,
    description: version.description,
    draft: {
      draft_revision: current.draft.draft_revision + 1,
      rules: cloneJson(version.rules),
      based_on_version_id: version.version_id,
    },
    updated_at: MOCK_DICTIONARY_UPDATED_AT,
    updated_by: cloneJson(actor),
  }
}

/**
 * Canned-пример `dictionary-atlas-general-restored-v1` допустим только при
 * выполнении его предусловий: он согласован с текущим состоянием, восстанавливает
 * именно запрошенную версию и не фабрикует `active_version_id`/`versions_count`.
 * Проверяем, что canned описывает ту же активную версию/число версий, что и
 * текущий справочник, его `based_on_version_id` совпадает с запрошенным
 * `version_id`, а `active_version_id` и `based_on_version_id` реально
 * присутствуют в истории (`PublishingStore`), — тогда нет «висячего» active и
 * нет подмены выбранной версии.
 */
function isCannedRestoreConsistent(
  store: PublishingStore,
  current: Dictionary,
  canned: Dictionary,
  requestedVersionId: string,
): boolean {
  const versionIds = new Set(
    store.listVersions(current.dictionary_id).map((item) => item.version_id),
  )
  const activeVersionId = canned.active_version_id
  return (
    canned.draft.draft_revision === current.draft.draft_revision + 1 &&
    canned.draft.based_on_version_id === requestedVersionId &&
    activeVersionId === current.active_version_id &&
    canned.versions_count === current.versions_count &&
    (activeVersionId === null || versionIds.has(activeVersionId)) &&
    versionIds.has(requestedVersionId)
  )
}

/**
 * Возвращает canned-пример `dictionary-atlas-general-restored-v1`, только если
 * он согласован с текущим состоянием и восстанавливает именно запрошенную
 * версию (канонический сценарий restore после publish v2: active v2, история
 * v1+v2, `versions_count=2`, запрошена v1). В остальных случаях собирает
 * согласованный `Dictionary` из выбранной версии, сохраняя
 * `active_version_id`/`versions_count` текущего справочника.
 */
function resolveRestoredDictionary(
  store: PublishingStore,
  current: Dictionary,
  version: DictionaryVersion,
  actor: Actor,
): Dictionary {
  const canned = store.getRestoreResult(current.dictionary_id)
  if (
    canned &&
    isCannedRestoreConsistent(store, current, canned, version.version_id)
  ) {
    return canned
  }
  return buildRestoredDictionary(current, version, actor)
}

/** GET /dictionaries/{dictionary_id}/versions → 200 | 401 | 404 | 422. */
export const listDictionaryVersionsHandler: MockHandler = ({
  controller,
  params,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parseVersionsLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const dictionary = controller.getDictionaryStore().get(params.dictionary_id)
  if (!dictionary) {
    return notFoundResponse(requestId)
  }

  const forcedError = controller.consumePublishingError('listDictionaryVersions')
  if (forcedError) {
    return declaredPublishingErrorResponse(requestId, forcedError)
  }

  const cursor = url.searchParams.get('cursor')
  const page = resolveVersionsPage(
    controller.getPublishingStore().listVersions(params.dictionary_id),
    { cursor, limit },
  )
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}

/**
 * GET /dictionaries/{dictionary_id}/versions/{version_id}
 * → 200 | 401 | 404.
 */
export const getDictionaryVersionHandler: MockHandler = ({
  controller,
  params,
  requestId,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const forcedError = controller.consumePublishingError('getDictionaryVersion')
  if (forcedError) {
    return declaredPublishingErrorResponse(requestId, forcedError)
  }

  const version = controller
    .getPublishingStore()
    .getVersion(params.dictionary_id, params.version_id)
  if (!version) {
    return notFoundResponse(requestId)
  }
  return jsonResponse(version, requestId)
}

/**
 * POST /dictionaries/{dictionary_id}/restore-draft
 * → 200 Dictionary (revision+1, based_on_version_id) | 401 | 403 | 404 | 409
 * DRAFT_VERSION_CONFLICT | 422 | управляемая ошибка.
 */
export const restoreDictionaryDraftHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, params, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('RestoreDictionaryDraftRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumePublishingError('restoreDictionaryDraft')
  if (forcedError) {
    return declaredPublishingErrorResponse(requestId, forcedError)
  }

  const dictionaryStore = controller.getDictionaryStore()
  const dictionary = dictionaryStore.get(params.dictionary_id)
  if (!dictionary) {
    return notFoundResponse(requestId)
  }

  const payload = body.value as RestoreDictionaryDraftRequest
  const store = controller.getPublishingStore()
  const version = store.getVersion(params.dictionary_id, payload.version_id)
  if (!version) {
    return notFoundResponse(requestId)
  }
  if (payload.expected_draft_revision !== dictionary.draft.draft_revision) {
    return declaredPublishingErrorResponse(requestId, 'DRAFT_VERSION_CONFLICT')
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const restored = resolveRestoredDictionary(store, dictionary, version, actor)
  dictionaryStore.put(restored)
  store.markRestoredDraft(params.dictionary_id, version.version_id)
  return jsonResponse(restored, requestId)
}

/**
 * POST /dictionaries/{dictionary_id}/publish
 * → 201 PublishedDictionaryResponse | 401 | 403 | 404 | 409
 * DRAFT_VERSION_CONFLICT/STALE_SIMULATION/RULE_CONFLICT/
 * NO_SCENARIO_ACK_REQUIRED/IDEMPOTENCY_KEY_REUSED | 422 | управляемая ошибка.
 */
export const publishDictionaryHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, params, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('PublishDictionaryRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const idempotencyKey = request.headers.get('Idempotency-Key')
  if (!idempotencyKey || idempotencyKey.trim().length === 0) {
    return missingIdempotencyKeyResponse(requestId)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  // Проверка принятого ключа идёт до staleness-проверок: потерянный ответ
  // принятой операции должен воспроизводиться даже при устаревшем тесте.
  const store = controller.getPublishingStore()
  const lookup = store.resolveOperation(
    actor.user_id,
    params.dictionary_id,
    idempotencyKey,
    body.value,
  )
  if (lookup) {
    if (lookup.kind === 'replay') {
      return jsonResponse(lookup.response, requestId, 201)
    }
    return declaredPublishingErrorResponse(requestId, 'IDEMPOTENCY_KEY_REUSED')
  }

  const forcedError = controller.consumePublishingError('publishDictionary')
  if (forcedError) {
    return declaredPublishingErrorResponse(requestId, forcedError)
  }

  const dictionaryStore = controller.getDictionaryStore()
  const dictionary = dictionaryStore.get(params.dictionary_id)
  if (!dictionary) {
    return notFoundResponse(requestId)
  }

  const payload = body.value as PublishDictionaryRequest
  const simulation = controller
    .getSimulationStore()
    .get(payload.simulation_id)
  if (!simulation || simulation.base.dictionary_id !== params.dictionary_id) {
    return notFoundResponse(requestId)
  }

  const currentRevision = dictionary.draft.draft_revision
  if (payload.expected_draft_revision !== currentRevision) {
    return declaredPublishingErrorResponse(requestId, 'DRAFT_VERSION_CONFLICT')
  }
  if (simulation.base.draft_revision !== currentRevision) {
    return declaredPublishingErrorResponse(requestId, 'STALE_SIMULATION')
  }
  const now = controller.getPublishingNow()
  if (
    now !== null &&
    Date.parse(simulation.base.expires_at) <= Date.parse(now)
  ) {
    return declaredPublishingErrorResponse(requestId, 'STALE_SIMULATION')
  }
  if (simulation.base.counts.rule_conflicts > 0) {
    return declaredPublishingErrorResponse(requestId, 'RULE_CONFLICT')
  }
  if (
    simulation.base.counts.no_scenario > 0 &&
    !payload.acknowledge_no_scenario
  ) {
    return declaredPublishingErrorResponse(requestId, 'NO_SCENARIO_ACK_REQUIRED')
  }

  const result = store.getPublishResult(
    params.dictionary_id,
    controller.getPublishingScenario(),
  )
  if (!result) {
    return notFoundResponse(requestId)
  }

  dictionaryStore.put(result.dictionary)
  store.appendVersion(result.published_version)
  store.setActiveRuleSet(result.rule_set)
  store.recordOperation(
    actor.user_id,
    params.dictionary_id,
    idempotencyKey,
    body.value,
    result,
  )
  return jsonResponse(result, requestId, 201)
}
