// Общие типы mock-инфраструктуры WiseWay.
//
// DTO берутся только из generated-типов единственного публичного OAS
// (`@/api/generated/schema`): ручные копии схем запрещены (FE §2, API §12).
// Mocks и real-потребители используют одну и ту же публичную схему.

import type { components } from '@/api/generated/schema'

import type { MockController } from './controller'

export type LoginRequest = components['schemas']['LoginRequest']
export type Session = components['schemas']['Session']
export type AppConfig = components['schemas']['AppConfig']
export type Root = components['schemas']['Root']
export type RootsResponse = components['schemas']['RootsResponse']
export type Company = components['schemas']['Company']
export type CompaniesResponse = components['schemas']['CompaniesResponse']
export type SearchRequest = components['schemas']['SearchRequest']
export type FacetRequest = components['schemas']['FacetRequest']
export type SearchResponse = components['schemas']['SearchResponse']
export type FacetResponse = components['schemas']['FacetResponse']
export type SearchFreshness = components['schemas']['SearchFreshness']
export type ErrorResponse = components['schemas']['ErrorResponse']
export type ErrorDetails = components['schemas']['ErrorDetails']
export type FieldError = components['schemas']['FieldError']
export type ErrorCode = components['schemas']['ErrorCode']

/** Контекст одного mock-запроса, передаваемый handler-у. */
export interface MockRequestContext {
  /** Сценарий/состояние mock-сервера. */
  controller: MockController
  /** Исходный `Request` без изменений. */
  request: Request
  /** Разобранный URL запроса (с абсолютным base для относительных адресов). */
  url: URL
  /** Безопасный `X-Request-ID` этого ответа; совпадает с `error.request_id`. */
  requestId: string
  /** Путь относительно префикса API, например `/health`. */
  path: string
}

/** Обработчик одной операции; возвращает готовый `Response`. */
export type MockHandler = (
  context: MockRequestContext,
) => Response | Promise<Response>
