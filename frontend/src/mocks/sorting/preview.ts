// Canned preview-сценарии и in-memory store для mock-операций
// `createSortingPreview`/`getSortingPreview` (LT-07.2b).
//
// Источник данных — только публичные примеры
// `contracts/examples/sorting/preview-*.json`. Mock не выполняет matcher,
// ranking, расчёт плана/целей, readiness-детектор и не перемещает файлы: каждый
// сценарий — literal `Preview` из примера. Predictions и CollisionDetails
// отдаются ровно так, как объявлено, включая nullable `target`/
// `existing_target_metadata`.
//
// Сценарий выбирается контроллером (`setPreviewScenario`) либо выводится из
// разрешённого снимка выбора: ALL_MATCHING → `allmatching-120`, EXPLICIT с
// одним элементом → `explicit-one`, EXPLICIT с несколькими →
// `explicit-multiple`. `hetero` (все Prediction/CollisionDetails kinds, nullable
// цели) и `conflict` (RULE_CONFLICT) выбираются явно, потому что они не
// выводятся из create-снимка.
//
// Объявлена только первая страница (у allmatching-120 непустой `next_cursor`),
// второй страницы в примерах нет, поэтому непустой `cursor` → 422, а mock не
// синтезирует страницу. `PreviewStore` хранит созданные preview по `preview_id`
// и не продлевает их `expires_at` при чтении.

import { cloneJson, getExample } from '../data'
import type { Preview, SelectionSnapshot } from '../types'

/** Управляемый preview-сценарий (LT-07.2b). */
export type PreviewScenario =
  | 'explicit-one'
  | 'explicit-multiple'
  | 'allmatching-120'
  | 'hetero'
  | 'conflict'

/** Порядок объявленных preview-сценариев. */
export const PREVIEW_SCENARIOS: readonly PreviewScenario[] = [
  'explicit-one',
  'explicit-multiple',
  'allmatching-120',
  'hetero',
  'conflict',
]

/** Id публичного примера `Preview` для каждого сценария. */
const PREVIEW_EXAMPLE_IDS: Record<PreviewScenario, string> = {
  'explicit-one': 'preview-atlas-explicit-one',
  'explicit-multiple': 'preview-atlas-explicit-multiple',
  'allmatching-120': 'preview-atlas-allmatching-120-page1',
  hetero: 'preview-atlas-hetero',
  conflict: 'preview-atlas-conflict',
}

/**
 * Возвращает копию literal `Preview` выбранного сценария. Rows/counts/targets/
 * collisions не пересчитываются.
 */
export function getCannedPreview(scenario: PreviewScenario): Preview {
  return getExample<Preview>(PREVIEW_EXAMPLE_IDS[scenario])
}

/**
 * Выводит сценарий из разрешённого снимка выбора: ALL_MATCHING →
 * `allmatching-120`; EXPLICIT с одним элементом → `explicit-one`, с несколькими →
 * `explicit-multiple`. Membership не вычисляется — только режим и `selected_count`
 * canned-снимка.
 */
export function derivePreviewScenario(
  snapshot: SelectionSnapshot,
): PreviewScenario {
  if (snapshot.mode === 'ALL_MATCHING') {
    return 'allmatching-120'
  }
  return snapshot.selected_count === 1 ? 'explicit-one' : 'explicit-multiple'
}

/** Сохранённый preview: literal payload + владелец. */
export interface StoredPreview {
  readonly preview: Preview
  /** `user_id` создателя; preview привязан к пользователю, не к сессии. */
  readonly ownerUserId: string
}

/**
 * In-memory store созданных preview с `reset()`. Чтение отдаёт сохранённый
 * `expires_at` без продления; `isExpired` доступен batch-листу (LT-07.2c), где
 * `STALE_PREVIEW` объявлен для `createSortingBatch`.
 */
export class PreviewStore {
  private readonly byId = new Map<string, StoredPreview>()

  /** Очищает все созданные preview (детерминированный reset). */
  reset(): void {
    this.byId.clear()
  }

  /** Сохраняет preview по его `preview_id`. */
  put(stored: StoredPreview): void {
    this.byId.set(stored.preview.preview_id, stored)
  }

  /** Сохранённый preview по `preview_id` или `undefined`. */
  get(previewId: string): StoredPreview | undefined {
    return this.byId.get(previewId)
  }

  /** Все сохранённые preview (копия, только чтение). */
  list(): StoredPreview[] {
    return [...this.byId.values()]
  }

  /**
   * Проверяет истёк ли preview при заданном `now` (Instant). `now === null`
   * отключает TTL-проверку. Чтение preview этот метод не вызывает: `get` не
   * объявляет 409 и не продлевает срок.
   */
  isExpired(previewId: string, now: string | null): boolean {
    if (now === null) {
      return false
    }
    const stored = this.byId.get(previewId)
    if (!stored) {
      return false
    }
    return Date.parse(now) >= Date.parse(stored.preview.expires_at)
  }
}

/** Параметры страницы `getSortingPreview`. */
export interface PreviewPageQuery {
  readonly cursor: string | null
}

/**
 * Разбирает `limit`; `null` — невалидное значение (вне 1..100). Объявленная
 * страница одна, поэтому `limit` только валидируется и не создаёт новых
 * страниц.
 */
export function parsePreviewLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

/**
 * Возвращает страницу preview. Объявлена только первая страница: `cursor ===
 * null` отдаёт literal пример, непустой курсор → `null` (handler отвечает 422
 * `VALIDATION_ERROR`, не выдумывая несуществующую страницу).
 */
export function resolvePreviewPage(
  preview: Preview,
  query: PreviewPageQuery,
): Preview | null {
  if (query.cursor !== null) {
    return null
  }
  return cloneJson(preview)
}
