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

/** Находит handler по методу и пути относительно префикса API. */
export function findMockHandler(
  method: string,
  path: string,
): MockHandler | undefined {
  return handlersByKey[`${method.toUpperCase()} ${path}`]
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

  const handler = findMockHandler(method, path)
  if (!handler) {
    return notFoundResponse(requestId)
  }

  const context: MockRequestContext = {
    controller,
    request,
    url,
    requestId,
    path,
  }
  return handler(context)
}
