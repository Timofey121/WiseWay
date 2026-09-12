// Загрузка публичных примеров контракта для mock-ответов.
//
// Источник данных — только `contracts/examples/**` (alias `@examples`),
// индексированный по `fixtures/synthetic/manifest.json`. Ручные копии DTO и
// выдуманные значения не создаются: mock отдаёт ровно те payload'ы, что
// проверены контрактными тестами. Модуль только читает JSON.
//
// `import.meta.glob` резолвит alias `@examples` в Vite/Vitest и даёт eager-карту
// файлов без отдельного загрузчика. Ключи карты нормализуются к пути
// относительно `contracts/examples/`, чтобы совпасть с полем `file` манифеста.

import manifest from '@fixtures/synthetic/manifest.json'

export interface ManifestExampleEntry {
  id: string
  schema: string | null
  file: string
  description?: string
  secret_note?: string
}

const exampleModules = import.meta.glob('@examples/**/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, unknown>

const manifestExamples: ManifestExampleEntry[] = (
  manifest as { examples?: ManifestExampleEntry[] }
).examples ?? []

/**
 * Приводит и путь манифеста (`contracts/examples/auth/x.json`), и ключ
 * glob-карты (`../contracts/examples/auth/x.json`) к единому виду
 * `auth/x.json`.
 */
export function toExamplesRelativePath(filePath: string): string {
  const normalized = filePath.replace(/\\/g, '/')
  const marker = 'contracts/examples/'
  const index = normalized.indexOf(marker)
  return index >= 0 ? normalized.slice(index + marker.length) : normalized
}

const moduleByRelativePath = new Map<string, unknown>()
for (const [key, value] of Object.entries(exampleModules)) {
  moduleByRelativePath.set(toExamplesRelativePath(key), value)
}

interface IndexedExample extends ManifestExampleEntry {
  value: unknown
}

const examplesById = new Map<string, IndexedExample>()
for (const entry of manifestExamples) {
  const value = moduleByRelativePath.get(toExamplesRelativePath(entry.file))
  if (value === undefined) {
    continue
  }
  examplesById.set(entry.id, { ...entry, value })
}

/** Глубокая копия JSON-значения: mock не отдаёт ссылку на общий пример. */
export function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** Проверяет, что пример с таким id есть в манифесте и загружен. */
export function hasExample(id: string): boolean {
  return examplesById.has(id)
}

/** Возвращает копию публичного примера по id из манифеста. */
export function getExample<T>(id: string): T {
  const entry = examplesById.get(id)
  if (!entry) {
    throw new Error(
      `Публичный пример "${id}" не найден: проверьте fixtures/synthetic/manifest.json и contracts/examples/`,
    )
  }
  return cloneJson(entry.value) as T
}

/** Возвращает schema-ref примера (`#/components/schemas/...`) или null. */
export function getExampleSchema(id: string): string | null {
  return examplesById.get(id)?.schema ?? null
}

/** Список id всех проиндексированных примеров. */
export function listExampleIds(): string[] {
  return [...examplesById.keys()]
}
