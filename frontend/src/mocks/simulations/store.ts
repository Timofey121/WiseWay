// In-memory хранилище симуляций для mock-операций
// `createDictionarySimulation`/`getSimulation` (LT-07.1b).
//
// Источник данных — только публичные примеры
// `contracts/examples/simulations/*.json` (индексируются по
// `fixtures/synthetic/manifest.json`). Планы, matcher, RuleSet и READY-набор
// здесь не вычисляются: store лишь хранит literal canned-сценарии и отдаёт
// объявленные страницы. Каждый сценарий — изолированный универсум со своей
// `draft_revision`, `base_rule_set` и `ready_snapshot_id`; mock не подменяет
// один сценарий другим.
//
// `reset()` восстанавливает детерминированный seed. Пейджинг воспроизводит
// объявленные страницы примеров (page1 → page2) по непрозрачному курсору;
// generic-курсор `sim-offset-<n>` используется, когда запрошенный `limit`
// создаёт границу, которой нет в примерах.

import { cloneJson, getExample } from '../data'
import type { PlanRow, Simulation } from '../types'

/** Управляемый сценарий симуляции (LT-07.1b). */
export type SimulationScenario =
  | 'full'
  | 'empty'
  | 'conflict'
  | 'same-target'
  | 'no-scenario'

/** Порядок объявленных сценариев. */
export const SIMULATION_SCENARIOS: readonly SimulationScenario[] = [
  'full',
  'empty',
  'conflict',
  'same-target',
  'no-scenario',
]

/**
 * Примеры одной симуляции. Для `full` это две объявленные страницы одного
 * `simulation_id`; остальные сценарии — одна страница.
 */
const SCENARIO_EXAMPLE_IDS: Record<SimulationScenario, readonly string[]> = {
  full: ['simulation-atlas-full-page1', 'simulation-atlas-full-page2'],
  empty: ['simulation-atlas-empty'],
  conflict: ['simulation-atlas-conflict'],
  'same-target': ['simulation-atlas-same-target'],
  'no-scenario': ['simulation-atlas-v3-restored'],
}

/**
 * Метаданные симуляции без страничных `rows`/`next_cursor` плюс полный
 * упорядоченный набор строк и объявленные границы страниц.
 */
export interface StoredSimulation {
  base: Omit<Simulation, 'rows' | 'next_cursor'>
  rows: PlanRow[]
  /** Размер первой объявленной страницы (default `limit` мока). */
  defaultPageSize: number
  /** Объявленный курсор → смещение строк. */
  cursorOffsets: Record<string, number>
}

/** Собирает stored-сценарий из объявленных страниц одного simulation_id. */
function buildStoredSimulation(pages: readonly Simulation[]): StoredSimulation {
  const first = pages[0]
  const rows = pages.flatMap((page) => cloneJson(page.rows))
  const cursorOffsets: Record<string, number> = {}
  let offset = 0
  for (let index = 0; index < pages.length - 1; index += 1) {
    offset += pages[index].rows.length
    const next = pages[index].next_cursor
    if (next) {
      cursorOffsets[next] = offset
    }
  }
  return {
    base: {
      simulation_id: first.simulation_id,
      dictionary_id: first.dictionary_id,
      draft_revision: first.draft_revision,
      base_rule_set: cloneJson(first.base_rule_set),
      ready_snapshot_id: first.ready_snapshot_id,
      created_at: first.created_at,
      expires_at: first.expires_at,
      total: first.total,
      counts: cloneJson(first.counts),
      warnings: cloneJson(first.warnings),
    },
    rows,
    defaultPageSize: Math.max(1, first.rows.length),
    cursorOffsets,
  }
}

/** Параметры страницы `getSimulation`. */
export interface SimulationPageQuery {
  cursor: string | null
  limit: number | null
}

const GENERATED_CURSOR_PATTERN = /^sim-offset-(\d+)$/

/** Разбирает generic-курсор `sim-offset-<n>`; `null` — не наш курсор. */
export function parseSimulationOffsetCursor(cursor: string): number | null {
  const match = GENERATED_CURSOR_PATTERN.exec(cursor)
  if (!match) {
    return null
  }
  return Number.parseInt(match[1], 10)
}

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseSimulationLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/** Объявленный курсор для смещения либо generic-курсор. */
function cursorForOffset(
  stored: StoredSimulation,
  offset: number,
): string {
  for (const [cursor, value] of Object.entries(stored.cursorOffsets)) {
    if (value === offset) {
      return cursor
    }
  }
  return `sim-offset-${offset}`
}

/**
 * Возвращает объявленную страницу симуляции. `cursor`/`limit` finite:
 * неизвестный курсор → `null` (handler отдаёт 422). Курсор может быть
 * объявленным примером (`cursor-simulation-atlas-full-page2`) или generic
 * (`sim-offset-<n>`) после явного `limit`.
 */
export function resolveSimulationPage(
  stored: StoredSimulation,
  query: SimulationPageQuery,
): Simulation | null {
  let offset = 0
  if (query.cursor !== null) {
    const declared = stored.cursorOffsets[query.cursor]
    if (declared !== undefined) {
      offset = declared
    } else {
      const generated = parseSimulationOffsetCursor(query.cursor)
      if (generated === null) {
        return null
      }
      offset = generated
    }
  }
  const pageSize = query.limit ?? stored.defaultPageSize
  const rows = stored.rows.slice(offset, offset + pageSize)
  const nextOffset = offset + pageSize
  const nextCursor =
    nextOffset < stored.rows.length
      ? cursorForOffset(stored, nextOffset)
      : null
  return {
    ...cloneJson(stored.base),
    rows: cloneJson(rows),
    next_cursor: nextCursor,
  }
}

/** In-memory store `simulation_id → StoredSimulation` с seed и `reset()`. */
export class SimulationStore {
  private readonly byId = new Map<string, StoredSimulation>()
  private readonly byScenario = new Map<SimulationScenario, StoredSimulation>()
  private readonly createdRevisions = new Map<string, number>()

  constructor() {
    this.reset()
  }

  /** Восстанавливает базовое состояние из публичных примеров контракта. */
  reset(): void {
    this.byId.clear()
    this.byScenario.clear()
    this.createdRevisions.clear()
    for (const scenario of SIMULATION_SCENARIOS) {
      const pages = SCENARIO_EXAMPLE_IDS[scenario].map((id) =>
        getExample<Simulation>(id),
      )
      const stored = buildStoredSimulation(pages)
      this.byScenario.set(scenario, stored)
      this.byId.set(stored.base.simulation_id, stored)
    }
  }

  /**
   * Фиксирует, что симуляция создана поверх текущей `draft_revision`
   * справочника, и заменяет ревизию в сохранённой странице. Так `getSimulation`
   * отдаёт ту же ревизию, что `GET /dictionary`, без staleness-проверок и без
   * 409: изменение черновика после создания не меняет сохранённый результат
   * (staleness — предмет publish, LT-07.1c).
   */
  markCreated(simulationId: string, dictionaryRevision: number): void {
    this.createdRevisions.set(simulationId, dictionaryRevision)
    const stored = this.byId.get(simulationId)
    if (!stored) {
      return
    }
    const updated: StoredSimulation = {
      ...stored,
      base: { ...stored.base, draft_revision: dictionaryRevision },
    }
    this.byId.set(simulationId, updated)
    for (const [scenario, value] of this.byScenario.entries()) {
      if (value.base.simulation_id === simulationId) {
        this.byScenario.set(scenario, updated)
      }
    }
  }

  /** Ревизия черновика на момент создания симуляции (или `undefined`). */
  getCreatedRevision(simulationId: string): number | undefined {
    return this.createdRevisions.get(simulationId)
  }

  /** Stored-сценарий по управляемому id. */
  getScenario(scenario: SimulationScenario): StoredSimulation {
    const found = this.byScenario.get(scenario)
    if (!found) {
      throw new Error(`Сценарий симуляции "${scenario}" отсутствует в store`)
    }
    return found
  }

  /** Stored-симуляция по `simulation_id` или `undefined`. */
  get(simulationId: string): StoredSimulation | undefined {
    return this.byId.get(simulationId)
  }
}
