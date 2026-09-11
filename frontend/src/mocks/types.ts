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
export type TargetDirectory = components['schemas']['TargetDirectory']
export type PageTargetDirectory = components['schemas']['PageTargetDirectory']
export type ResolveTargetRequest = components['schemas']['ResolveTargetRequest']
export type Rule = components['schemas']['Rule']
export type DictionaryDraft = components['schemas']['DictionaryDraft']
export type Dictionary = components['schemas']['Dictionary']
export type DictionaryListResponse =
  components['schemas']['DictionaryListResponse']
export type DictionaryVersion = components['schemas']['DictionaryVersion']
export type PageDictionaryVersion =
  components['schemas']['PageDictionaryVersion']
export type PublishedDictionaryResponse =
  components['schemas']['PublishedDictionaryResponse']
export type PublishDictionaryRequest =
  components['schemas']['PublishDictionaryRequest']
export type RestoreDictionaryDraftRequest =
  components['schemas']['RestoreDictionaryDraftRequest']
export type CreateDictionaryRequest =
  components['schemas']['CreateDictionaryRequest']
export type ReplaceDictionaryDraftRequest =
  components['schemas']['ReplaceDictionaryDraftRequest']
export type CreateSimulationRequest =
  components['schemas']['CreateSimulationRequest']
export type Simulation = components['schemas']['Simulation']
export type PlanRow = components['schemas']['PlanRow']
export type PlanCounts = components['schemas']['PlanCounts']
export type RuleSet = components['schemas']['RuleSet']
export type RuleReference = components['schemas']['RuleReference']
export type Actor = components['schemas']['Actor']
export type QueueState = components['schemas']['QueueState']
export type QueueFilters = components['schemas']['QueueFilters']
export type QueueItem = components['schemas']['QueueItem']
export type QueueQueryRequest = components['schemas']['QueueQueryRequest']
export type QueueResponse = components['schemas']['QueueResponse']
export type SelectionItem = components['schemas']['SelectionItem']
export type ExplicitSelectionRequest =
  components['schemas']['ExplicitSelectionRequest']
export type AllMatchingSelectionRequest =
  components['schemas']['AllMatchingSelectionRequest']
export type SelectionRequest = components['schemas']['SelectionRequest']
export type SelectionSnapshot = components['schemas']['SelectionSnapshot']
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
  /**
   * Извлечённые path-параметры шаблона маршрута (например `company_id`,
   * `dictionary_id`). Для статических путей — пустой объект.
   */
  params: Record<string, string>
}

/** Обработчик одной операции; возвращает готовый `Response`. */
export type MockHandler = (
  context: MockRequestContext,
) => Response | Promise<Response>
