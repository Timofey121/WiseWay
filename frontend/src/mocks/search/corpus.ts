// Детерминированный materializer синтетического корпуса (LT-06.2a-i).
//
// Источник данных — только `fixtures/synthetic/corpus.json` (alias `@fixtures`).
// Модуль раскрывает `files[]` и `cohorts[]` в полные schema-valid `SearchItem`,
// строит контекстный каталог `Marker` из `marker_model.contexts` и не выполняет
// никакого поиска, ранжирования или парсинга путей. Раскрытие cohort — literal
// подстановка `{index}` с `index_pad`; ничего не вычисляется по содержимому.
//
// `SearchItem.markers` содержит только распознанные VALUE-родителей (требование
// LT-03.1b: UNRECOGNIZED-терминалы остаются в каталоге отдельно, для
// selected_markers/фасетов). Терминальный UNRECOGNIZED-маркер конкретного
// отклонения выводится из `structure_issue.level_id` и доступен через
// `getUnrecognizedMarker`, но не входит в `item.markers`.
//
// DTO берутся из generated-типов единственного OAS (`@/api/generated/schema`);
// ручные копии публичных схем запрещены.

import corpusFixture from '@fixtures/synthetic/corpus.json'

import type { components } from '@/api/generated/schema'

export type SearchItem = components['schemas']['SearchItem']
export type Marker = components['schemas']['Marker']
export type StructureIssue = components['schemas']['StructureIssue']
export type SearchFreshness = components['schemas']['SearchFreshness']
export type Facet = components['schemas']['Facet']
export type FacetOption = components['schemas']['FacetOption']

interface RawMarkerValue {
  value_id: string
  level_id: string
  raw_value: string | null
  display_value: string
  kind: 'VALUE' | 'UNRECOGNIZED'
}

interface RawContext {
  context_id: string
  root_id: string
  path: string[]
}

interface RawRoot {
  root_id: string
  display_prefix: string
}

interface RawFileRecord {
  item_id: string
  root_id: string
  relative_path: string
  filename?: string
  display_path?: string
  extension?: string
  size_bytes?: number
  modified_at?: string
  structure_status?: 'VALID' | 'UNRECOGNIZED'
  structure_issue?: StructureIssue
  marker_context?: string
}

interface RawCohort {
  cohort_id: string
  root_id: string
  count: number
  index_start?: number
  index_pad?: number
  item_id_pattern: string
  relative_path_pattern: string
  filename_pattern?: string
  display_path_pattern?: string
  extension?: string
  size_bytes?: number
  modified_at?: string
  marker_context?: string
}

interface RawCorpus {
  defaults: {
    modified_at: string
    size_bytes: number
    structure_status: 'VALID' | 'UNRECOGNIZED'
  }
  roots: RawRoot[]
  files: RawFileRecord[]
  cohorts: RawCohort[]
  marker_model: {
    levels: Record<string, string>
    values: RawMarkerValue[]
    contexts: RawContext[]
  }
}

interface CatalogEntry {
  marker: Marker
  rootId: string
  path: string[]
}

const corpus = corpusFixture as unknown as RawCorpus

/** Копия `Marker`: resolver не отдаёт ссылку на общий каталог. */
export function cloneMarker(marker: Marker): Marker {
  return { ...marker }
}

/** Копия `SearchItem` вместе с вложенными `location`/`markers`/`structure_issue`. */
export function cloneSearchItem(item: SearchItem): SearchItem {
  return {
    ...item,
    location: { ...item.location },
    markers: item.markers.map(cloneMarker),
    structure_issue: item.structure_issue ? { ...item.structure_issue } : null,
  }
}

const markerValueIndex = new Map<string, RawMarkerValue>()
for (const value of corpus.marker_model.values) {
  markerValueIndex.set(value.value_id, value)
}

const rootIndex = new Map<string, RawRoot>()
for (const root of corpus.roots) {
  rootIndex.set(root.root_id, root)
}

const catalogEntries = new Map<string, CatalogEntry>()
const contextChains = new Map<string, string[]>()

function markerIdFor(rootId: string, path: string[]): string {
  return `marker-${rootId}-${path.join('-')}`
}

// Раскрытие объявленных контекстов в маркеры: каждый префикс пути даёт маркер
// своего уровня. ID стабилен и контекстно-уникален по root + цепочке value_id.
for (const context of corpus.marker_model.contexts) {
  const chain: string[] = []
  for (let length = 1; length <= context.path.length; length += 1) {
    const prefix = context.path.slice(0, length)
    const leaf = markerValueIndex.get(prefix[prefix.length - 1])
    if (!leaf) {
      throw new Error(
        `Контекст "${context.context_id}" ссылается на неизвестное значение "${prefix[prefix.length - 1]}"`,
      )
    }
    const markerId = markerIdFor(context.root_id, prefix)
    const marker: Marker = {
      marker_id: markerId,
      level_id: leaf.level_id,
      level_name: corpus.marker_model.levels[leaf.level_id] ?? leaf.level_id,
      raw_value: leaf.raw_value,
      display_value: leaf.display_value,
      kind: leaf.kind,
    }
    const existing = catalogEntries.get(markerId)
    if (existing && JSON.stringify(existing.marker) !== JSON.stringify(marker)) {
      throw new Error(`marker_id "${markerId}" конфликтует по идентичности`)
    }
    catalogEntries.set(markerId, {
      marker,
      rootId: context.root_id,
      path: prefix,
    })
    chain.push(markerId)
  }
  contextChains.set(context.context_id, chain)
}

function basename(relativePath: string): string {
  const separator = relativePath.lastIndexOf('/')
  return separator >= 0 ? relativePath.slice(separator + 1) : relativePath
}

function displayPathFor(rootId: string, relativePath: string): string {
  const root = rootIndex.get(rootId)
  if (!root) {
    throw new Error(`Корень "${rootId}" отсутствует в корпусе`)
  }
  return `${root.display_prefix.replace(/\/+$/, '')}/${relativePath}`
}

function chainFor(record: { item_id: string; marker_context?: string }): string[] {
  if (!record.marker_context) {
    return []
  }
  const chain = contextChains.get(record.marker_context)
  if (!chain) {
    throw new Error(
      `Запись "${record.item_id}" ссылается на неизвестный marker_context "${record.marker_context}"`,
    )
  }
  return chain
}

function materializeRecord(record: RawFileRecord): SearchItem {
  const chain = chainFor(record)
  return {
    item_id: record.item_id,
    location: {
      root_id: record.root_id,
      relative_path: record.relative_path,
      display_path:
        record.display_path ??
        displayPathFor(record.root_id, record.relative_path),
    },
    filename: record.filename ?? basename(record.relative_path),
    markers: chain.map((markerId) => {
      const entry = catalogEntries.get(markerId)
      if (!entry) {
        throw new Error(`Маркер "${markerId}" отсутствует в каталоге`)
      }
      return cloneMarker(entry.marker)
    }),
    extension: record.extension ?? '',
    size_bytes: record.size_bytes ?? corpus.defaults.size_bytes,
    modified_at: record.modified_at ?? corpus.defaults.modified_at,
    structure_status: record.structure_status ?? corpus.defaults.structure_status,
    structure_issue: record.structure_issue ?? null,
  }
}

// Literal-раскрытие cohort: только `{index}` и `index_pad`; без поиска.
function expandCohort(cohort: RawCohort): RawFileRecord[] {
  const pad = cohort.index_pad ?? 4
  const start = cohort.index_start ?? 1
  const records: RawFileRecord[] = []
  for (let offset = 0; offset < cohort.count; offset += 1) {
    const index = String(start + offset).padStart(pad, '0')
    const expand = (pattern?: string): string | undefined =>
      pattern ? pattern.replaceAll('{index}', index) : undefined
    records.push({
      item_id: expand(cohort.item_id_pattern) as string,
      root_id: cohort.root_id,
      relative_path: expand(cohort.relative_path_pattern) as string,
      filename: expand(cohort.filename_pattern),
      display_path: expand(cohort.display_path_pattern),
      extension: cohort.extension,
      size_bytes: cohort.size_bytes,
      modified_at: cohort.modified_at,
      marker_context: cohort.marker_context,
    })
  }
  return records
}

// Терминальный UNRECOGNIZED-маркер отклонения: строится из последнего
// распознанного родителя и значения `unrecognized-<level>`. В `item.markers`
// не входит (см. шапку модуля).
function deriveUnrecognizedMarker(record: RawFileRecord): Marker | null {
  const status = record.structure_status ?? corpus.defaults.structure_status
  const issue = record.structure_issue
  if (status !== 'UNRECOGNIZED' || !issue || issue.level_id === null) {
    return null
  }
  const value = corpus.marker_model.values.find(
    (candidate) =>
      candidate.kind === 'UNRECOGNIZED' && candidate.level_id === issue.level_id,
  )
  if (!value) {
    return null
  }
  const chain = chainFor(record)
  const last = chain[chain.length - 1]
  if (!last) {
    return null
  }
  const entry = catalogEntries.get(`${last}-${value.value_id}`)
  return entry ? cloneMarker(entry.marker) : null
}

const inventory = new Map<string, SearchItem>()
const unrecognizedMarkers = new Map<string, Marker>()

const allRecords: RawFileRecord[] = [
  ...corpus.files,
  ...corpus.cohorts.flatMap(expandCohort),
]

for (const record of allRecords) {
  const item = materializeRecord(record)
  inventory.set(item.item_id, item)
  const unrecognized = deriveUnrecognizedMarker(record)
  if (unrecognized) {
    unrecognizedMarkers.set(item.item_id, unrecognized)
  }
}

const markerCatalog = new Map<string, Marker>()
for (const [markerId, entry] of catalogEntries) {
  markerCatalog.set(markerId, entry.marker)
}

/** Полный materialized-инвентарь `item_id → SearchItem` (files + cohorts). */
export const inventoryById: ReadonlyMap<string, SearchItem> = inventory

/** Контекстный каталог `marker_id → Marker` из `marker_model.contexts`. */
export const markerCatalogById: ReadonlyMap<string, Marker> = markerCatalog

/** Возвращает копию `SearchItem` по `item_id` или `undefined`. */
export function getSearchItem(itemId: string): SearchItem | undefined {
  const item = inventory.get(itemId)
  return item ? cloneSearchItem(item) : undefined
}

/** Возвращает копию `Marker` по `marker_id` или `undefined`. */
export function getMarker(markerId: string): Marker | undefined {
  const marker = markerCatalog.get(markerId)
  return marker ? cloneMarker(marker) : undefined
}

/**
 * Терминальный UNRECOGNIZED-маркер первого отклонения записи или `undefined`.
 * Для `UNEXPECTED_DEPTH` (`level_id === null`) уровня нет.
 */
export function getUnrecognizedMarker(itemId: string): Marker | undefined {
  const marker = unrecognizedMarkers.get(itemId)
  return marker ? cloneMarker(marker) : undefined
}

/** Число записей materialized-инвентаря. */
export function inventorySize(): number {
  return inventory.size
}

/** Число уникальных `marker_id` в каталоге. */
export function markerCatalogSize(): number {
  return markerCatalog.size
}

/** Список `item_id` materialized-инвентаря в порядке раскрытия корпуса. */
export function listInventoryItemIds(): string[] {
  return [...inventory.keys()]
}

/** Список `marker_id` каталога. */
export function listMarkerIds(): string[] {
  return [...markerCatalog.keys()]
}
