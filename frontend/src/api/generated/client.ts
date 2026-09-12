// Типизированный runtime-клиент WiseWay API.
//
// Клиент строится поверх generated-типов (`schema.ts`) через `openapi-fetch` и
// не содержит ручных DTO: path/query/body/headers выводятся из единственного
// публичного OAS. Реальная и mock-реализации используют одну и ту же схему;
// переключение режима — это только подмена `baseUrl`/`fetch`.

import createClient, { type Client } from 'openapi-fetch'

import type { paths } from './schema'

/** Типизированный клиент всех операций WiseWay API. */
export type WiseWayApiClient = Client<paths>

export interface WiseWayClientOptions {
  /**
   * Корень API. По умолчанию `/api/v1` — префикс из `servers` публичного OAS
   * (UI и API на одном origin). Для mock-режима сюда подставляется адрес
   * перехватчика.
   */
  baseUrl?: string
  /**
   * Пользовательская реализация `fetch`. В тестах и mock-режиме позволяет
   * отвечать из сценариев без реального сервера. По умолчанию используется
   * `globalThis.fetch`.
   */
  fetch?: (input: Request) => Promise<Response>
}

/**
 * Создаёт типизированный клиент WiseWay API.
 *
 * @example
 * const api = createWiseWayClient()
 * const { data } = await api.GET('/health')
 */
export function createWiseWayClient(
  options: WiseWayClientOptions = {},
): WiseWayApiClient {
  return createClient<paths>({
    baseUrl: options.baseUrl ?? '/api/v1',
    fetch: options.fetch,
  })
}
