// POST /sorting/previews (createSortingPreview) и
// GET /sorting/previews/{preview_id} (getSortingPreview) — LT-07.2b.
//
// Операции отдают literal canned-сценарии из
// `contracts/examples/sorting/preview-*.json`: EXPLICIT one/multiple,
// allmatching-120 (page1), hetero (все Prediction/CollisionDetails kinds,
// nullable цели) и conflict (RULE_CONFLICT). Mock не выполняет matcher,
// ranking, расчёт плана/целей и не перемещает файлы: preview — только прогноз.
//
// `createSortingPreview` — объявленная мутация (`csrf: true`): требует активную
// mock-сессию и корректный `X-CSRF-Token`, валидирует `PreviewCreateRequest`
// (`selection_id`), разрешает снимок через `SelectionStore.resolve` и отдаёт
// owner/expiry/unknown строго объявленными кодами: другой `user_id` → 403
// `FORBIDDEN`, истёкший `expires_at` → 409 `SELECTION_EXPIRED`, неизвестный id
// → 404 `NOT_FOUND`. Сценарий выбирает контроллер либо выводит из снимка
// (EXPLICIT one/multiple, ALL_MATCHING 120). 201 — literal `Preview`.
//
// `getSortingPreview` — чтение: требует только активную mock-сессию, отдаёт
// сохранённую страницу (`cursor === null`), неизвестный id → 404, непустой
// `cursor`/невалидный `limit` → 422. 409 у чтения не объявлен и не
// возвращается; чтение не продлевает `expires_at` (срок остаётся прежним).

import { readJsonBody } from '../body'
import { requireSessionAndCsrf } from '../guards'
import {
  invalidBodyResponse,
  jsonResponse,
  unauthenticatedResponse,
  validationErrorResponse,
} from '../responses'
import { previewErrorResponse } from '../sorting/errors'
import {
  derivePreviewScenario,
  getCannedPreview,
  parsePreviewLimit,
  resolvePreviewPage,
} from '../sorting/preview'
import type { MockHandler, Preview, PreviewCreateRequest } from '../types'
import { toFieldErrors, validateSchema } from '../validate'

/** Безопасная ошибка недействительного курсора страницы. */
const CURSOR_ERROR = {
  field: 'cursor',
  code: 'CURSOR',
  message: 'Курсор страницы недействителен.',
} as const

/**
 * Привязывает literal canned-preview к разрешённому снимку: `selection_id` и
 * `company_id` берутся из снимка, чтобы прогноз ссылался именно на запрошенный
 * выбор. Rows/counts/rule_set/targets/collisions остаются literal примера.
 */
function bindPreviewToSelection(preview: Preview, selection: PreviewSelection): Preview {
  return {
    ...preview,
    selection_id: selection.selection_id,
    company_id: selection.company_id,
  }
}

/** Минимальные поля разрешённого снимка, нужные preview. */
interface PreviewSelection {
  readonly selection_id: string
  readonly company_id: string
}

/**
 * POST /sorting/previews
 * → 201 Preview (literal canned) | 401 | 403 FORBIDDEN/CSRF_FAILED |
 * 404 NOT_FOUND | 409 SELECTION_EXPIRED | 422 | управляемая ошибка.
 */
export const createSortingPreviewHandler: MockHandler = async (context) => {
  const guard = requireSessionAndCsrf(context)
  if (guard) {
    return guard
  }
  const { controller, request, requestId } = context

  const body = await readJsonBody(request)
  if (!body.ok) {
    return invalidBodyResponse(requestId)
  }
  const validation = validateSchema('PreviewCreateRequest', body.value)
  if (!validation.valid) {
    return validationErrorResponse(requestId, toFieldErrors(validation.errors))
  }

  const forcedError = controller.consumePreviewError('createSortingPreview')
  if (forcedError) {
    return previewErrorResponse(requestId, forcedError)
  }

  const actor = controller.getSession()?.actor
  if (!actor) {
    return unauthenticatedResponse(requestId)
  }

  const payload = body.value as PreviewCreateRequest
  const resolution = controller
    .getSelectionStore()
    .resolve(payload.selection_id, {
      actorId: actor.user_id,
      now: controller.getSelectionNow(),
    })
  if (resolution.kind === 'not_found') {
    return previewErrorResponse(requestId, 'NOT_FOUND')
  }
  if (resolution.kind === 'forbidden') {
    return previewErrorResponse(requestId, 'FORBIDDEN')
  }
  if (resolution.kind === 'expired') {
    return previewErrorResponse(requestId, 'SELECTION_EXPIRED')
  }

  const selection = resolution.selection
  const scenario =
    controller.getPreviewScenario() ??
    derivePreviewScenario(selection.snapshot)
  const preview = bindPreviewToSelection(getCannedPreview(scenario), {
    selection_id: selection.snapshot.selection_id,
    company_id: selection.snapshot.company_id,
  })
  controller.getPreviewStore().put({ preview, ownerUserId: actor.user_id })
  return jsonResponse(preview, requestId, 201)
}

/**
 * GET /sorting/previews/{preview_id}
 * → 200 Preview (сохранённая страница) | 401 | 403 | 404 | 422 (cursor/limit) |
 * управляемая ошибка. 409 не объявлен и не возвращается; `expires_at` не
 * продлевается чтением.
 */
export const getSortingPreviewHandler: MockHandler = ({
  controller,
  params,
  requestId,
  url,
}) => {
  if (!controller.isAuthenticated()) {
    return unauthenticatedResponse(requestId)
  }

  const limitRaw = url.searchParams.get('limit')
  const limit = limitRaw === null ? null : parsePreviewLimit(limitRaw)
  if (limitRaw !== null && limit === null) {
    return validationErrorResponse(requestId, [
      {
        field: 'limit',
        code: 'LIMIT',
        message: 'Размер страницы должен быть от 1 до 100.',
      },
    ])
  }

  const stored = controller.getPreviewStore().get(params.preview_id)
  if (!stored) {
    return previewErrorResponse(requestId, 'NOT_FOUND')
  }

  const forcedError = controller.consumePreviewError('getSortingPreview')
  if (forcedError) {
    return previewErrorResponse(requestId, forcedError)
  }

  const cursor = url.searchParams.get('cursor')
  const page = resolvePreviewPage(stored.preview, { cursor })
  if (!page) {
    return validationErrorResponse(requestId, [CURSOR_ERROR])
  }
  return jsonResponse(page, requestId)
}
