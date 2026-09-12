// In-memory хранилище снимков выбора для mock-операции
// `createSortingSelection` (LT-07.2a).
//
// Источник данных — только публичные примеры
// `contracts/examples/sorting/selection-snapshot-*.json`. Mock не выполняет
// matcher, readiness-детектор и не вычисляет membership: EXPLICIT-снимок
// выбирается canned-примером по числу переданных элементов, ALL_MATCHING —
// canned-примером `selection-snapshot-all-matching-120` с literal
// `selected_count`/`queue_generation` текущего canned-сценария очереди.
// `selected_count` ALL_MATCHING равен `expected_eligible_count` только после
// сверки с текущим eligible_count; при расхождении снимок не создаётся
// (409 `SELECTION_CHANGED`).
//
// Store хранит созданные снимки (с владельцем-user_id и замороженными
// элементами), поэтому поздние поступления не меняют уже созданный снимок.
// `resolve()` воспроизводит семантику использования снимка (owner/expiry/
// unknown) для следующих листьев preview/batch: другой user_id → `forbidden`,
// истёкший `expires_at` → `expired`, неизвестный id → `not_found`. Сама
// create-операция снимок не «использует» и потому эти статусы не возвращает
// (они не объявлены для `createSortingSelection` в OAS).

import { getExample } from '../data'
import type {
  QueueResponse,
  SelectionItem,
  SelectionRequest,
  SelectionSnapshot,
} from '../types'

/** Предел одной партии из `fixtures/synthetic/queue_selections.json`. */
export const MAX_BATCH_ITEMS = 1000

/** Замороженный элемент снимка (IDs/revisions хранит сервер, не браузер). */
export interface FrozenSelectionMember {
  readonly item_id: string
  readonly item_revision: number
}

/** Сохранённый снимок выбора: literal snapshot + владелец + frozen members. */
export interface StoredSelection {
  readonly snapshot: SelectionSnapshot
  /** `user_id` создателя; снимок привязан к пользователю, не к сессии. */
  readonly ownerUserId: string
  /** Замороженные элементы; для ALL_MATCHING остаются server-side. */
  readonly members: readonly FrozenSelectionMember[]
}

/** Результат разрешения снимка для использования (preview/batch). */
export type SelectionResolution =
  | { readonly kind: 'found'; readonly selection: StoredSelection }
  | { readonly kind: 'forbidden' }
  | { readonly kind: 'expired' }
  | { readonly kind: 'not_found' }

/** Параметры разрешения снимка. */
export interface SelectionResolveOptions {
  /** `user_id` использующего; снимок доступен только создателю. */
  readonly actorId: string
  /** Инъектированное «текущее время» (Instant) или `null` без TTL-проверки. */
  readonly now: string | null
}

/** In-memory store созданных снимков выбора с `reset()`. */
export class SelectionStore {
  private readonly byId = new Map<string, StoredSelection>()

  /** Очищает все созданные снимки (детерминированный reset). */
  reset(): void {
    this.byId.clear()
  }

  /** Сохраняет снимок по его `selection_id`. */
  put(selection: StoredSelection): void {
    this.byId.set(selection.snapshot.selection_id, selection)
  }

  /** Снимок по `selection_id` или `undefined`. */
  get(selectionId: string): StoredSelection | undefined {
    return this.byId.get(selectionId)
  }

  /** Все сохранённые снимки (копия, только чтение). */
  list(): StoredSelection[] {
    return [...this.byId.values()]
  }

  /**
   * Разрешает использование снимка: неизвестный → `not_found`; другой
   * владелец → `forbidden`; истёкший (при заданном `now`) → `expired`; иначе
   * `found`. Проверка владельца идёт до TTL, как в API §7/§8.
   */
  resolve(
    selectionId: string,
    options: SelectionResolveOptions,
  ): SelectionResolution {
    const selection = this.byId.get(selectionId)
    if (!selection) {
      return { kind: 'not_found' }
    }
    if (selection.ownerUserId !== options.actorId) {
      return { kind: 'forbidden' }
    }
    if (
      options.now !== null &&
      Date.parse(options.now) >= Date.parse(selection.snapshot.expires_at)
    ) {
      return { kind: 'expired' }
    }
    return { kind: 'found', selection }
  }
}

/** Результат создания снимка `createSortingSelection`. */
export type SelectionCreation =
  | { readonly kind: 'created'; readonly selection: StoredSelection }
  | { readonly kind: 'empty' }
  | { readonly kind: 'limit' }
  | { readonly kind: 'changed' }

/** Контекст создания снимка: текущий canned-queue и владелец. */
export interface SelectionCreationContext {
  /** Canned `QueueResponse` выбранного queue-сценария. */
  readonly currentQueue: QueueResponse
  /**
   * Переопределение текущего eligible_count для проверки
   * `expected_eligible_count` mismatch; `null` — использовать canned значение.
   */
  readonly eligibleCountOverride: number | null
  /** `user_id` создателя снимка. */
  readonly ownerUserId: string
}

/** Id canned-снимка EXPLICIT по числу выбранных элементов. */
const EXPLICIT_ONE_EXAMPLE_ID = 'selection-snapshot-explicit-one'
const EXPLICIT_MULTIPLE_EXAMPLE_ID = 'selection-snapshot-explicit-multiple'
const ALL_MATCHING_EXAMPLE_ID = 'selection-snapshot-all-matching-120'

function freezeItems(items: readonly SelectionItem[]): FrozenSelectionMember[] {
  return items.map((item) => ({
    item_id: item.item_id,
    item_revision: item.item_revision,
  }))
}

/** Собирает EXPLICIT-снимок из canned-примера с literal selected_count. */
function buildExplicitSelection(
  request: Extract<SelectionRequest, { mode: 'EXPLICIT' }>,
  ownerUserId: string,
): StoredSelection {
  const exampleId =
    request.items.length === 1
      ? EXPLICIT_ONE_EXAMPLE_ID
      : EXPLICIT_MULTIPLE_EXAMPLE_ID
  const snapshot = getExample<SelectionSnapshot>(exampleId)
  return {
    snapshot: {
      ...snapshot,
      company_id: request.company_id,
      selected_count: request.items.length,
    },
    ownerUserId,
    members: freezeItems(request.items),
  }
}

/** Собирает ALL_MATCHING-снимок из canned-примера после сверки counts. */
function buildAllMatchingSelection(
  request: Extract<SelectionRequest, { mode: 'ALL_MATCHING' }>,
  context: SelectionCreationContext,
): StoredSelection {
  const snapshot = getExample<SelectionSnapshot>(ALL_MATCHING_EXAMPLE_ID)
  return {
    snapshot: {
      ...snapshot,
      company_id: request.company_id,
      selected_count: request.expected_eligible_count,
      queue_generation: context.currentQueue.queue_generation,
    },
    ownerUserId: context.ownerUserId,
    // Полный список IDs/revisions ALL_MATCHING хранит сервер (API §7); браузер
    // его не пересылает, поэтому в снимке он не дублируется.
    members: [],
  }
}

/**
 * Разрешает создание снимка строго по canned-значениям:
 *  * ALL_MATCHING с нулём eligible → `empty` (422 `EMPTY_SELECTION`);
 *  * ALL_MATCHING сверх `MAX_BATCH_ITEMS` → `limit` (422
 *    `BATCH_LIMIT_EXCEEDED` без усечения);
 *  * `expected_eligible_count` ≠ текущему eligible → `changed` (409
 *    `SELECTION_CHANGED`);
 *  * иначе — `created` с literal canned-снимком.
 * EXPLICIT не зависит от eligible_count и всегда даёт `created`.
 */
export function resolveSelectionCreation(
  request: SelectionRequest,
  context: SelectionCreationContext,
): SelectionCreation {
  if (request.mode === 'EXPLICIT') {
    return {
      kind: 'created',
      selection: buildExplicitSelection(request, context.ownerUserId),
    }
  }

  const eligible =
    context.eligibleCountOverride ?? context.currentQueue.eligible_count
  if (eligible === 0) {
    return { kind: 'empty' }
  }
  if (eligible > MAX_BATCH_ITEMS) {
    return { kind: 'limit' }
  }
  if (request.expected_eligible_count !== eligible) {
    return { kind: 'changed' }
  }
  return {
    kind: 'created',
    selection: buildAllMatchingSelection(request, context),
  }
}
