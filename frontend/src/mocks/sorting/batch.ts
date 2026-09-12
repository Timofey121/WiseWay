// Canned batch-сценарии и in-memory store для mock-операций
// `createSortingBatch`/`getSortingBatch`/`listSortingBatches` (LT-07.2c).
//
// Источник данных — только публичные примеры
// `contracts/examples/sorting/batch-*.json` (индексируются по
// `fixtures/synthetic/manifest.json`). Mock не выполняет claim, executor,
// matcher, перемещение файлов, не считает progress и не реализует
// recovery/снимки: каждый сценарий — literal `Batch`/`BatchPage` из примера.
//
// Модель:
//  * `BatchScenario` — изолированный canned-универсум партии (свои
//    `batch_id`, `selection_id`, `rule_set`, counts и outcomes). Сценарий
//    выбирает контроллер (`setBatchScenario`) либо он выводится из
//    `execution_mode` DIRECT/PREVIEWED.
//  * `BatchPhase` — фаза прогресса (`ACCEPTED`→`RUNNING`→`COMPLETED`/
//    `COMPLETED_WITH_ISSUES`/`RECOVERY_REQUIRED`). `setBatchPhase` позволяет
//    `getSortingBatch` отдавать прогрессирующие canned-страницы без реальных
//    таймеров; фаза отображается в сценарий (`PHASE_SCENARIO`).
//  * `BatchStore` хранит принятые партии (literal страницы + identity),
//    умеет выдавать уникальный `batch_id` для новой операции, ведёт
//    идемпотентность (actor + key + body fingerprint) и собирает
//    `BatchSummary` из сохранённых партий.
//
// `bindBatchPage` привязывает identity сохранённой партии к canned-странице
// выбранной фазы: `batch_id`/`company_id`/`selection_id`/`preview_id`/`actor`/
// `rule_set`/`created_at` берутся из принятой партии, а `status`, counts,
// outcomes, timestamps прогресса и `next_cursor` — literal примера. Поэтому
// GET по созданному id остаётся самосогласованным, а прогресс/варианты
// состояний воспроизводимы canned-сценариями.
//
// `seedHistory()` заполняет store семью literal-партиями
// `batch-history-atlas-page1`, чтобы `listSortingBatches` воспроизводил
// объявленную историю (created_at DESC, batch_id DESC).

import { fingerprintBody } from '@/api/idempotency'

import { cloneJson, getExample } from '../data'
import type { Actor, Batch, BatchSummary, RuleSet } from '../types'

/** Изолированный canned-универсум партии. */
export type BatchScenario =
  | 'direct-fresh'
  | 'previewed-fresh'
  | 'sorted'
  | 'conflict'
  | 'hetero'
  | 'technical'
  | 'same-user-session'

/** Порядок объявленных batch-сценариев. */
export const BATCH_SCENARIOS: readonly BatchScenario[] = [
  'direct-fresh',
  'previewed-fresh',
  'sorted',
  'conflict',
  'hetero',
  'technical',
  'same-user-session',
]

/** Фаза прогресса партии (без реального исполнителя). */
export type BatchPhase =
  | 'ACCEPTED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'COMPLETED_WITH_ISSUES'
  | 'RECOVERY_REQUIRED'

/** Порядок объявленных фаз прогресса. */
export const BATCH_PHASES: readonly BatchPhase[] = [
  'ACCEPTED',
  'RUNNING',
  'COMPLETED',
  'COMPLETED_WITH_ISSUES',
  'RECOVERY_REQUIRED',
]

/** Id публичных примеров `Batch` для каждого сценария (page1, page2, …). */
const BATCH_EXAMPLE_IDS: Record<BatchScenario, readonly string[]> = {
  'direct-fresh': [
    'batch-atlas-direct-fresh-page1',
    'batch-atlas-direct-fresh-page2',
  ],
  'previewed-fresh': [
    'batch-atlas-previewed-fresh-page1',
    'batch-atlas-previewed-fresh-page2',
  ],
  sorted: ['batch-atlas-sorted'],
  conflict: ['batch-atlas-conflict'],
  hetero: ['batch-atlas-hetero'],
  technical: ['batch-atlas-technical'],
  'same-user-session': ['batch-atlas-same-user-session'],
}

/** Каноническая фаза canned-сценария. */
const SCENARIO_PHASE: Record<BatchScenario, BatchPhase> = {
  'direct-fresh': 'ACCEPTED',
  'previewed-fresh': 'RUNNING',
  sorted: 'COMPLETED',
  conflict: 'COMPLETED_WITH_ISSUES',
  hetero: 'COMPLETED_WITH_ISSUES',
  technical: 'RECOVERY_REQUIRED',
  'same-user-session': 'COMPLETED_WITH_ISSUES',
}

/** Сценарий по умолчанию для фазы прогресса. */
export const PHASE_SCENARIO: Record<BatchPhase, BatchScenario> = {
  ACCEPTED: 'direct-fresh',
  RUNNING: 'previewed-fresh',
  COMPLETED: 'sorted',
  COMPLETED_WITH_ISSUES: 'hetero',
  RECOVERY_REQUIRED: 'technical',
}

/** Сценарии, входящие в literal-историю `batch-history-atlas-page1`. */
const HISTORY_SCENARIOS: readonly BatchScenario[] = [
  'technical',
  'sorted',
  'conflict',
  'hetero',
  'same-user-session',
  'previewed-fresh',
  'direct-fresh',
]

/** Все literal-страницы сценария (копии, не ссылки на примеры). */
export function getCannedBatchPages(scenario: BatchScenario): Batch[] {
  return BATCH_EXAMPLE_IDS[scenario].map((id) => getExample<Batch>(id))
}

/** Первая (принятая/текущая) страница сценария. */
export function getCannedBatchPage1(scenario: BatchScenario): Batch {
  return getExample<Batch>(BATCH_EXAMPLE_IDS[scenario][0])
}

/** Каноническая фаза сценария. */
export function canonicalPhase(scenario: BatchScenario): BatchPhase {
  return SCENARIO_PHASE[scenario]
}

/**
 * Возвращает literal-страницу сценария по непрозрачному курсору: `null` —
 * первая страница; `cursor` = `next_cursor` предыдущей страницы — следующая.
 * Неизвестный курсор → `null` (handler отвечает 422 и не выдумывает страницу).
 */
export function resolveCannedBatchPage(
  scenario: BatchScenario,
  cursor: string | null,
): Batch | null {
  const pages = getCannedBatchPages(scenario)
  if (cursor === null) {
    return pages[0]
  }
  for (let index = 1; index < pages.length; index += 1) {
    if (pages[index - 1].next_cursor === cursor) {
      return pages[index]
    }
  }
  return null
}

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseBatchLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/** Identity принятой партии, привязываемая к canned-странице. */
export interface BatchIdentity {
  readonly batch_id: string
  readonly company_id: string
  readonly selection_id: string
  readonly preview_id: string | null
  readonly actor: Actor
  readonly rule_set: RuleSet
  readonly created_at: string
}

/** Извлекает identity из literal-страницы (для seed/созданных партий). */
export function identityFromBatch(batch: Batch): BatchIdentity {
  return {
    batch_id: batch.batch_id,
    company_id: batch.company_id,
    selection_id: batch.selection_id,
    preview_id: batch.preview_id,
    actor: cloneJson(batch.actor),
    rule_set: cloneJson(batch.rule_set),
    created_at: batch.created_at,
  }
}

/**
 * Привязывает identity принятой партии к canned-странице: status/counts/
 * outcomes/прогресс остаются literal выбранной фазы, а идентификаторы —
 * согласованы с созданной партией.
 */
export function bindBatchPage(page: Batch, identity: BatchIdentity): Batch {
  return {
    ...cloneJson(page),
    ...cloneJson(identity),
  }
}

/** Сохранённая принятая партия. */
export interface StoredBatch {
  readonly identity: BatchIdentity
  readonly scenario: BatchScenario
  /** Literal 202-ответ (page1), привязанный к identity. */
  readonly response: Batch
}

/** Сохранённая идемпотентная операция создания партии. */
export interface StoredBatchOperation {
  readonly key: string
  readonly actorId: string
  readonly bodyFingerprint: string
  readonly stored: StoredBatch
}

/** Результат проверки Idempotency-Key в store. */
export type BatchOperationLookup =
  | { readonly kind: 'replay'; readonly stored: StoredBatch }
  | { readonly kind: 'reused' }

/** Ключ ячейки операции: actor + Idempotency-Key. */
function operationKey(actorId: string, key: string): string {
  return `${actorId}\u0000${key}`
}

const HISTORY_CURSOR_PATTERN = /^batches-offset-(\d+)$/

/** Параметры страницы `listSortingBatches`. */
export interface BatchHistoryQuery {
  readonly cursor: string | null
  readonly limit: number | null
}

/**
 * Собирает `BatchSummary` из literal-партии (без вычисления counts/progress).
 */
export function toBatchSummary(batch: Batch): BatchSummary {
  return {
    batch_id: batch.batch_id,
    company_id: batch.company_id,
    actor: cloneJson(batch.actor),
    status: batch.status,
    created_at: batch.created_at,
    finished_at: batch.finished_at,
    selected_count: batch.selected_count,
    completed_count: batch.completed_count,
    counts: cloneJson(batch.counts),
  }
}

/**
 * Finite-страница истории партий: порядок `created_at DESC`, затем
 * `batch_id DESC`; `cursor` — непрозрачный `batches-offset-<n>`. Неизвестный
 * курсор → `null` (handler отвечает 422).
 */
export function resolveBatchHistoryPage(
  summaries: readonly BatchSummary[],
  query: BatchHistoryQuery,
): { items: BatchSummary[]; next_cursor: string | null } | null {
  let offset = 0
  if (query.cursor !== null) {
    const match = HISTORY_CURSOR_PATTERN.exec(query.cursor)
    if (!match) {
      return null
    }
    offset = Number.parseInt(match[1], 10)
  }
  const pageSize = query.limit ?? 100
  const items = summaries.slice(offset, offset + pageSize)
  const nextOffset = offset + pageSize
  const nextCursor =
    nextOffset < summaries.length ? `batches-offset-${nextOffset}` : null
  return { items: cloneJson(items), next_cursor: nextCursor }
}

/** In-memory store принятых партий и идемпотентных операций с `reset()`. */
export class BatchStore {
  private readonly byId = new Map<string, StoredBatch>()
  private readonly operations = new Map<string, StoredBatchOperation>()
  private sequence = 0

  /** Очищает все партии и идемпотентные операции. */
  reset(): void {
    this.byId.clear()
    this.operations.clear()
    this.sequence = 0
  }

  /** Партия по `batch_id` или `undefined`. */
  get(batchId: string): StoredBatch | undefined {
    return this.byId.get(batchId)
  }

  /** Все сохранённые партии (копия, только чтение). */
  list(): StoredBatch[] {
    return [...this.byId.values()]
  }

  /** Сохраняет партию по её `batch_id`. */
  put(stored: StoredBatch): void {
    this.byId.set(stored.identity.batch_id, stored)
  }

  /**
   * Выдаёт уникальный `batch_id`: literal canned id для первой партии
   * сценария, детерминированный суффикс — для последующих (новая операция
   * создаёт новую партию).
   */
  allocateBatchId(baseId: string): string {
    if (!this.byId.has(baseId)) {
      return baseId
    }
    this.sequence += 1
    return `${baseId}-${this.sequence}`
  }

  /**
   * Заполняет store семью literal-партиями истории
   * `batch-history-atlas-page1`, чтобы список воспроизводил объявленный
   * порядок. Идемпотентно: повторный вызов не создаёт дублей.
   */
  seedHistory(): void {
    for (const scenario of HISTORY_SCENARIOS) {
      const page = getCannedBatchPage1(scenario)
      this.put({
        scenario,
        identity: identityFromBatch(page),
        response: page,
      })
    }
  }

  /**
   * `BatchSummary` компании в порядке `created_at DESC`, `batch_id DESC`.
   * Counts/status — literal сохранённых партий, не пересчитываются.
   */
  listSummaries(companyId: string): BatchSummary[] {
    return this.list()
      .filter((stored) => stored.identity.company_id === companyId)
      .map((stored) => toBatchSummary(stored.response))
      .sort((left, right) => {
        const byCreated = right.created_at.localeCompare(left.created_at)
        if (byCreated !== 0) {
          return byCreated
        }
        return right.batch_id.localeCompare(left.batch_id)
      })
  }

  /**
   * Ищет сохранённую операцию создания партии по actor/ключу: `replay` при
   * совпадении отпечатка тела, `reused` при другом теле, `undefined` если
   * ключ ещё не принимался.
   */
  resolveOperation(
    actorId: string,
    key: string,
    body: unknown,
  ): BatchOperationLookup | undefined {
    const record = this.operations.get(operationKey(actorId, key))
    if (!record) {
      return undefined
    }
    if (record.bodyFingerprint === fingerprintBody(body)) {
      return { kind: 'replay', stored: record.stored }
    }
    return { kind: 'reused' }
  }

  /** Сохраняет принятую операцию создания партии для идемпотентного повтора. */
  recordOperation(
    actorId: string,
    key: string,
    body: unknown,
    stored: StoredBatch,
  ): void {
    this.operations.set(operationKey(actorId, key), {
      key,
      actorId,
      bodyFingerprint: fingerprintBody(body),
      stored,
    })
  }
}
