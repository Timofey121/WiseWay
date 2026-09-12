// Разбор `Request` и диспетчеризация в mock-handlers.
//
// Router принимает fetch-совместимый `Request`, нормализует путь к префиксу
// `/api/v1`, применяет управляемую задержку контроллера и вызывает handler
// соответствующей операции. Неизвестный маршрут даёт безопасную 404
// `NOT_FOUND` (`ErrorResponse`), без правдоподобного успеха и без утечки
// деталей.

import type { MockController } from './controller'
import { handlersByKey } from './handlers'
import { notFoundResponse } from './responses'
import type { MockHandler, MockRequestContext } from './types'

/** Публичный префикс API из `servers` OAS. */
export const API_PREFIX = '/api/v1'

/**
 * Приводит путь запроса к виду относительно `/api/v1`. Абсолютный URL и
 * относительный pathname обрабатываются одинаково; запрос без префикса
 * маршрутизируется как есть.
 */
export function toApiPath(pathname: string): string {
  if (pathname === API_PREFIX) {
    return '/'
  }
  if (pathname.startsWith(`${API_PREFIX}/`)) {
    return pathname.slice(API_PREFIX.length)
  }
  return pathname
}

/**
 * Сопоставляет шаблон пути вида `/companies/{company_id}/dictionaries` с
 * конкретным путём, возвращая извлечённые параметры или `null`. Сегменты
 * `{name}` захватывают ровно один сегмент; число сегментов должно совпадать.
 */
function matchPathTemplate(
  template: string,
  path: string,
): Record<string, string> | null {
  const templateSegments = template.split('/').filter((segment) => segment !== '')
  const pathSegments = path.split('/').filter((segment) => segment !== '')
  if (templateSegments.length !== pathSegments.length) {
    return null
  }
  const params: Record<string, string> = {}
  for (let index = 0; index < templateSegments.length; index += 1) {
    const templateSegment = templateSegments[index]
    const pathSegment = pathSegments[index]
    if (templateSegment.startsWith('{') && templateSegment.endsWith('}')) {
      const name = templateSegment.slice(1, -1)
      params[name] = decodeURIComponent(pathSegment)
    } else if (templateSegment !== pathSegment) {
      return null
    }
  }
  return params
}

export interface MatchedMockRoute {
  handler: MockHandler
  params: Record<string, string>
}

/**
 * Находит handler и path-параметры по методу и пути. Сначала проверяется точное
 * совпадение (статический маршрут), затем — шаблоны с `{param}` в порядке
 * регистрации. Неизвестный маршрут даёт `undefined`.
 */
export function matchMockRoute(
  method: string,
  path: string,
): MatchedMockRoute | undefined {
  const upperMethod = method.toUpperCase()
  const exact = handlersByKey[`${upperMethod} ${path}`]
  if (exact) {
    return { handler: exact, params: {} }
  }
  for (const [key, handler] of Object.entries(handlersByKey)) {
    const separator = key.indexOf(' ')
    if (key.slice(0, separator) !== upperMethod) {
      continue
    }
    const params = matchPathTemplate(key.slice(separator + 1), path)
    if (params) {
      return { handler, params }
    }
  }
  return undefined
}

/** Находит handler по методу и пути относительно префикса API. */
export function findMockHandler(
  method: string,
  path: string,
): MockHandler | undefined {
  return matchMockRoute(method, path)?.handler
}

/**
 * Обрабатывает один mock-запрос: выдаёт `X-Request-ID`, применяет задержку и
 * возвращает `Response`. Задержка применяется и к неизвестным маршрутам, чтобы
 * сценарий был воспроизводим.
 */
export async function routeMockRequest(
  request: Request,
  controller: MockController,
): Promise<Response> {
  const requestId = controller.nextRequestId()
  const url = new URL(request.url, 'http://localhost')
  const method = request.method.toUpperCase()
  const path = toApiPath(url.pathname)

  await controller.wait()

  const matched = matchMockRoute(method, path)
  if (!matched) {
    return notFoundResponse(requestId)
  }

  const context: MockRequestContext = {
    controller,
    request,
    url,
    requestId,
    path,
    params: matched.params,
  }
  return matched.handler(context)
}
