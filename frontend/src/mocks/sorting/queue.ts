// Canned-сценарии очереди компании для mock-операции `querySortingQueue`
// (LT-07.2a).
//
// Источник данных — только публичные примеры `contracts/examples/sorting/
// queue-*.json` (индексируются по `fixtures/synthetic/manifest.json`). Mock не
// выполняет matcher, readiness-детектор, подсчёт counters/matching_count/
// eligible_count и не вычисляет membership: каждый сценарий — literal
// `QueueResponse` из примера. `counters`/`status_counts`/`matching_count`/
// `eligible_count`/`queue_generation`/`next_cursor` отдаются ровно так, как
// объявлено в примере.
//
// Примеры объявляют только первую страницу (`limit=100`). Второй страницы в
// публичных примерах нет, поэтому mock не синтезирует её: непустой `cursor`
// отклоняется handler-ом как `422 VALIDATION_ERROR`, а не превращается в
// правдоподобную, но выдуманную страницу.

import { getExample } from '../data'
import type { QueueFilters, QueueResponse } from '../types'

/**
 * Управляемый сценарий очереди (LT-07.2a): 0/120/1001 готовых, все активные
 * 0/120, явный MISSING и literal `query_text`.
 */
export type QueueScenario =
  | 'ready-120'
  | 'ready-0'
  | 'ready-1001'
  | 'all-active-120'
  | 'all-active-0'
  | 'missing-explicit'
  | 'query-text'

/** Порядок объявленных queue-сценариев. */
export const QUEUE_SCENARIOS: readonly QueueScenario[] = [
  'ready-120',
  'ready-0',
  'ready-1001',
  'all-active-120',
  'all-active-0',
  'missing-explicit',
  'query-text',
]

/** Id публичного примера `QueueResponse` для каждого сценария. */
const QUEUE_EXAMPLE_IDS: Record<QueueScenario, string> = {
  'ready-120': 'queue-ready-120-page1',
  'ready-0': 'queue-ready-0',
  'ready-1001': 'queue-ready-1001-page1',
  'all-active-120': 'queue-all-active-120',
  'all-active-0': 'queue-all-active-0',
  'missing-explicit': 'queue-missing-explicit',
  'query-text': 'queue-query-text',
}

/**
 * Объявленные фильтры каждого canned-сценария. Handler принимает сценарий
 * контроллера только если запрос описывает те же фильтры: иначе literal-ответ
 * не соответствовал бы запросу, и mock не отдаёт правдоподобный, но неверный
 * успех.
 */
const QUEUE_SCENARIO_FILTERS: Record<
  QueueScenario,
  { readonly statuses: readonly string[]; readonly queryText: string }
> = {
  'ready-120': { statuses: ['READY'], queryText: '' },
  'ready-0': { statuses: ['READY'], queryText: '' },
  'ready-1001': { statuses: ['READY'], queryText: '' },
  'all-active-120': { statuses: [], queryText: '' },
  'all-active-0': { statuses: [], queryText: '' },
  'missing-explicit': { statuses: ['MISSING'], queryText: '' },
  'query-text': { statuses: ['READY'], queryText: 'report-0001' },
}

/**
 * Возвращает `true`, если фильтры запроса совпадают с объявленными фильтрами
 * выбранного canned-сценария. `statuses` сравниваются как множества,
 * `query_text` — без учёта регистра (API §7).
 */
export function matchesQueueScenarioFilters(
  scenario: QueueScenario,
  filters: QueueFilters,
): boolean {
  const declared = QUEUE_SCENARIO_FILTERS[scenario]
  if (declared.statuses.length !== filters.statuses.length) {
    return false
  }
  const declaredStatuses = new Set(declared.statuses)
  if (!filters.statuses.every((status) => declaredStatuses.has(status))) {
    return false
  }
  return (
    declared.queryText.toLowerCase() === filters.query_text.trim().toLowerCase()
  )
}

/**
 * Возвращает копию literal `QueueResponse` выбранного сценария. Значения
 * counters/status_counts/счётчиков/generation/next_cursor не пересчитываются.
 */
export function getCannedQueueResponse(scenario: QueueScenario): QueueResponse {
  return getExample<QueueResponse>(QUEUE_EXAMPLE_IDS[scenario])
}

/**
 * Разрешает запрошенную страницу canned-ответа. Объявлена только первая
 * страница, поэтому `cursor === null` отдаёт literal пример, а непустой курсор
 * даёт `null` (handler отвечает `422 VALIDATION_ERROR`, не выдумывая страницу).
 */
export function resolveCannedQueuePage(
  canned: QueueResponse,
  cursor: string | null,
): QueueResponse | null {
  if (cursor !== null) {
    return null
  }
  return canned
}
