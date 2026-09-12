// Загрузчик и literal-resolver golden-сценариев поиска и фасетов (LT-06.2a-i).
//
// Источник истины — `fixtures/synthetic/search_expectations.json` (alias
// `@fixtures`). Resolver только ищет сценарий по request и материализует
// полный schema-valid `SearchResponse`/`FacetResponse` из literal-значений
// golden и materialized-инвентаря/каталога (`./corpus`). Он не выполняет
// matcher, ranking, парсинг путей и не вычисляет membership/total/facets: если
// сценарий не найден — возвращается `undefined`, вычисленного fallback нет.
//
// `request_state_id` ответа всегда эхо исходного request: mock отвечает на
// конкретную отправку, а не на ID, записанный в golden.

import searchExpectationsFixture from '@fixtures/synthetic/search_expectations.json'

import type { components } from '@/api/generated/schema'

import { getMarker, getSearchItem } from './corpus'
import type { Facet, FacetOption, Marker, SearchFreshness } from './corpus'

export type SearchResponse = components['schemas']['SearchResponse']
export type FacetResponse = components['schemas']['FacetResponse']
export type FreshnessStatus = SearchFreshness['status']

/** Условия поиска без `request_state_id` (он уникален для каждой отправки). */
export interface SearchScenarioLookupRequest {
  request_state_id: string
  root_id: string
  selected_marker_ids: readonly string[]
  query_text: string
  sort: { field: string; direction: string }
  facet_prefix: string
}

/** Условия открытия отдельного списка уровня (без сортировки). */
export interface FacetScenarioLookupRequest {
  request_state_id: string
  root_id: string
  selected_marker_ids: readonly string[]
  query_text: string
  facet_prefix: string
}

export interface SearchScenarioOptions {
  /**
   * Профиль freshness для разрешения коллизий условий, различающихся только
   * свежестью (`SRCH-Q011-FRESHNESS-UPDATING`, `SRCH-Q003-FRESHNESS-STALE`).
   * По умолчанию CURRENT; точный `request_state_id` имеет приоритет.
   */
  freshnessProfile?: FreshnessStatus
}

interface GoldenFacetLiteral {
  level_id: string
  level_name: string
  options: { marker_id: string; count: number }[]
}

interface GoldenSearchScenario {
  scenario_id: string
  request: SearchScenarioLookupRequest
  expected: {
    mode: 'IDLE' | 'RESULTS'
    total: number | null
    returned_count: number
    result_limit: number
    limited: boolean
    applied_query_text: string
    item_ids: string[]
    next_facet: GoldenFacetLiteral | null
  }
  freshness_profile?: FreshnessStatus
}

interface GoldenFacetScenario {
  scenario_id: string
  request: FacetScenarioLookupRequest
  expected: {
    facet_level_id: string | null
    options: { marker_id: string; count: number }[]
  }
}

interface GoldenConstants {
  ranking_profile_version: string
  freshness_profiles: Record<FreshnessStatus, SearchFreshness>
  roots: Record<string, { schema_set_version: string; index_generation: string }>
  level_names: Record<string, string>
}

interface SearchExpectations {
  constants: GoldenConstants
  search_scenarios: GoldenSearchScenario[]
  facet_scenarios: GoldenFacetScenario[]
}

const expectations = searchExpectationsFixture as unknown as SearchExpectations

function scenarioFreshness(scenario: GoldenSearchScenario): FreshnessStatus {
  return scenario.freshness_profile ?? 'CURRENT'
}

function sameStringArray(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  )
}

function sameSearchConditions(
  scenario: SearchScenarioLookupRequest,
  request: SearchScenarioLookupRequest,
): boolean {
  return (
    scenario.root_id === request.root_id &&
    scenario.query_text === request.query_text &&
    scenario.facet_prefix === request.facet_prefix &&
    scenario.sort.field === request.sort.field &&
    scenario.sort.direction === request.sort.direction &&
    sameStringArray(scenario.selected_marker_ids, request.selected_marker_ids)
  )
}

function sameFacetConditions(
  scenario: FacetScenarioLookupRequest,
  request: FacetScenarioLookupRequest,
): boolean {
  return (
    scenario.root_id === request.root_id &&
    scenario.query_text === request.query_text &&
    scenario.facet_prefix === request.facet_prefix &&
    sameStringArray(scenario.selected_marker_ids, request.selected_marker_ids)
  )
}

function requireMarker(markerId: string): Marker {
  const marker = getMarker(markerId)
  if (!marker) {
    throw new Error(
      `Golden-сценарий ссылается на отсутствующий marker_id "${markerId}"`,
    )
  }
  return marker
}

function facetOptions(
  literal: { marker_id: string; count: number }[],
): FacetOption[] {
  return literal.map((option) => ({
    ...requireMarker(option.marker_id),
    count: option.count,
  }))
}

function materializeSearchResponse(
  scenario: GoldenSearchScenario,
  request: SearchScenarioLookupRequest,
): SearchResponse {
  const constants = expectations.constants
  const rootConstants = constants.roots[request.root_id]
  const nextFacet = scenario.expected.next_facet
  return {
    request_state_id: request.request_state_id,
    mode: scenario.expected.mode,
    root_id: request.root_id,
    schema_set_version: rootConstants.schema_set_version,
    index_generation: rootConstants.index_generation,
    ranking_profile_version: constants.ranking_profile_version,
    applied_query_text: scenario.expected.applied_query_text,
    selected_markers: request.selected_marker_ids.map(requireMarker),
    total: scenario.expected.total,
    returned_count: scenario.expected.returned_count,
    result_limit: scenario.expected.result_limit,
    limited: scenario.expected.limited,
    items: scenario.expected.item_ids.map((itemId) => {
      const item = getSearchItem(itemId)
      if (!item) {
        throw new Error(
          `Golden-сценарий ссылается на отсутствующий item_id "${itemId}"`,
        )
      }
      return item
    }),
    next_facet: nextFacet
      ? {
          level_id: nextFacet.level_id,
          level_name: nextFacet.level_name,
          options: facetOptions(nextFacet.options),
        }
      : null,
    freshness: { ...constants.freshness_profiles[scenarioFreshness(scenario)] },
  }
}

function materializeFacetResponse(
  scenario: GoldenFacetScenario,
  request: FacetScenarioLookupRequest,
): FacetResponse {
  const constants = expectations.constants
  const rootConstants = constants.roots[request.root_id]
  const levelId = scenario.expected.facet_level_id
  const facet: Facet | null =
    levelId === null
      ? null
      : {
          level_id: levelId,
          level_name: constants.level_names[levelId] ?? levelId,
          options: facetOptions(scenario.expected.options),
        }
  return {
    request_state_id: request.request_state_id,
    root_id: request.root_id,
    schema_set_version: rootConstants.schema_set_version,
    index_generation: rootConstants.index_generation,
    facet,
  }
}

/**
 * Разрешает search-сценарий по условиям запроса и возвращает полный
 * `SearchResponse`, либо `undefined`, если такого golden-сценария нет.
 *
 * Точное совпадение `request_state_id` внутри подходящих условий имеет
 * приоритет; иначе выбирается сценарий запрошенного профиля freshness
 * (CURRENT по умолчанию). Это literal lookup, а не matcher.
 */
export function resolveSearchScenario(
  request: SearchScenarioLookupRequest,
  options: SearchScenarioOptions = {},
): SearchResponse | undefined {
  const candidates = expectations.search_scenarios.filter((scenario) =>
    sameSearchConditions(scenario.request, request),
  )
  if (candidates.length === 0) {
    return undefined
  }
  const exact = candidates.find(
    (scenario) => scenario.request.request_state_id === request.request_state_id,
  )
  if (exact) {
    return materializeSearchResponse(exact, request)
  }
  const profile = options.freshnessProfile ?? 'CURRENT'
  const byProfile = candidates.filter(
    (scenario) => scenarioFreshness(scenario) === profile,
  )
  const chosen = (byProfile.length > 0 ? byProfile : candidates)[0]
  return materializeSearchResponse(chosen, request)
}

/**
 * Разрешает facet-сценарий по условиям запроса и возвращает полный
 * `FacetResponse`, либо `undefined`, если такого golden-сценария нет.
 */
export function resolveFacetScenario(
  request: FacetScenarioLookupRequest,
): FacetResponse | undefined {
  const candidates = expectations.facet_scenarios.filter((scenario) =>
    sameFacetConditions(scenario.request, request),
  )
  if (candidates.length === 0) {
    return undefined
  }
  const exact = candidates.find(
    (scenario) => scenario.request.request_state_id === request.request_state_id,
  )
  const chosen = exact ?? candidates[0]
  return materializeFacetResponse(chosen, request)
}

/** Число golden search-сценариев. */
export function searchScenarioCount(): number {
  return expectations.search_scenarios.length
}

/** Число golden facet-сценариев. */
export function facetScenarioCount(): number {
  return expectations.facet_scenarios.length
}

/** Идентификаторы golden search-сценариев в порядке фикстуры. */
export function listSearchScenarioIds(): string[] {
  return expectations.search_scenarios.map((scenario) => scenario.scenario_id)
}

/** Идентификаторы golden facet-сценариев в порядке фикстуры. */
export function listFacetScenarioIds(): string[] {
  return expectations.facet_scenarios.map((scenario) => scenario.scenario_id)
}
