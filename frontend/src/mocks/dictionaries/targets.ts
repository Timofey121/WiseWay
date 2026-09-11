// Каталог разрешённых целевых каталогов и resolver синтетического display_path
// для mock-операций `listTargetDirectories`/`resolveTargetDirectory` (LT-07.1a).
//
// Источник данных — literal-фикстура `fixtures/synthetic/rule_expectations.json`
// (`target_directories` с `company_id`, `root_id`, `relative_directory` и общим
// `target_display_prefix`). Никакого файлового доступа, проверки существования
// каталога или matcher здесь нет: resolver выполняет только поиск по
// настроенному allowlist компании и не создаёт каталоги.
//
// `display_path` собирается как `<target_display_prefix>/<relative_directory>` —
// ровно та же literal-схема, что и в публичных примерах
// `contracts/examples/targets/*.json`.

import ruleExpectations from '@fixtures/synthetic/rule_expectations.json'

import type { PageTargetDirectory, TargetDirectory } from '../types'
import { validateSchema } from '../validate'

interface FixtureTargetDirectory {
  target_id: string
  company_id: string
  root_id: string
  relative_directory: string
}

interface RuleExpectationsFixture {
  target_display_prefix: string
  target_directories: FixtureTargetDirectory[]
}

const fixture = ruleExpectations as unknown as RuleExpectationsFixture

const DISPLAY_PREFIX = fixture.target_display_prefix
const ALLOWED_ROOT_PREFIX = `${DISPLAY_PREFIX}/`

interface CatalogEntry extends TargetDirectory {
  company_id: string
}

/**
 * Allowlist компании в стабильном порядке фикстуры. Порядок не вычисляется
 * matcher'ом и не зависит от filesystem.
 */
const TARGET_CATALOG: readonly CatalogEntry[] = fixture.target_directories.map(
  (target) => ({
    company_id: target.company_id,
    root_id: target.root_id,
    relative_directory: target.relative_directory,
    display_path: `${DISPLAY_PREFIX}/${target.relative_directory}`,
  }),
)

/** Разрешённые цели одной компании (копии без служебного `company_id`). */
export function listCompanyTargets(companyId: string): TargetDirectory[] {
  return TARGET_CATALOG.filter((target) => target.company_id === companyId).map(
    (target) => ({
      root_id: target.root_id,
      relative_directory: target.relative_directory,
      display_path: target.display_path,
    }),
  )
}

/**
 * Проверяет, что каноническая ссылка `{root_id, relative_directory}` входит в
 * настроенный allowlist компании. Используется валидацией `Rule.target` при
 * сохранении черновика; каталог не создаётся.
 */
export function isAllowedTarget(
  companyId: string,
  rootId: string,
  relativeDirectory: string,
): boolean {
  return TARGET_CATALOG.some(
    (target) =>
      target.company_id === companyId &&
      target.root_id === rootId &&
      target.relative_directory === relativeDirectory,
  )
}

/** Результат разрешения display_path. */
export type ResolveTargetResult =
  | { ok: true; target: TargetDirectory }
  | { ok: false; code: 'INVALID_TARGET' | 'PATH_OUTSIDE_ROOT' | 'VALIDATION_ERROR' }

/**
 * Разрешает синтетический `display_path` в существующую разрешённую цель
 * компании. Допустим только префикс `DEMO:/SandboxRoot/`; произвольный
 * компьютерный путь и путь вне корня отклоняются. Каталог не создаётся.
 */
export function resolveTargetDisplayPath(
  companyId: string,
  displayPath: string,
): ResolveTargetResult {
  if (!displayPath.startsWith('DEMO:')) {
    return { ok: false, code: 'INVALID_TARGET' }
  }
  if (!displayPath.startsWith(ALLOWED_ROOT_PREFIX)) {
    return { ok: false, code: 'PATH_OUTSIDE_ROOT' }
  }
  const relativeDirectory = displayPath.slice(ALLOWED_ROOT_PREFIX.length)
  if (!validateSchema('RelativeDirectory', relativeDirectory).valid) {
    return { ok: false, code: 'VALIDATION_ERROR' }
  }
  const match = TARGET_CATALOG.find(
    (target) =>
      target.company_id === companyId &&
      target.relative_directory === relativeDirectory,
  )
  if (!match) {
    return { ok: false, code: 'INVALID_TARGET' }
  }
  return {
    ok: true,
    target: {
      root_id: match.root_id,
      relative_directory: match.relative_directory,
      display_path: match.display_path,
    },
  }
}

const CURSOR_PATTERN = /^t(\d+)$/

/** Разбирает непрозрачный курсор страницы; `null` — невалидный курсор. */
export function parseTargetCursor(cursor: string): number | null {
  const match = CURSOR_PATTERN.exec(cursor)
  if (!match) {
    return null
  }
  return Number.parseInt(match[1], 10)
}

/** Разбирает `limit`; `null` — невалидное значение (вне 1..100). */
export function parseTargetLimit(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null
  }
  const value = Number.parseInt(raw, 10)
  return value >= 1 && value <= 100 ? value : null
}

export interface TargetListQuery {
  companyId: string
  prefix: string
  cursor: string | null
  limit: number
}

/**
 * Finite-страница разрешённых целей компании: фильтр по регистронезависимому
 * началу `relative_directory`, затем срез `[offset, offset+limit)` и
 * `next_cursor` следующей страницы. Алгоритм только читает literal-каталог.
 */
export function listTargetsPage(query: TargetListQuery): PageTargetDirectory {
  const all = listCompanyTargets(query.companyId)
  const prefix = query.prefix.toLowerCase()
  const filtered =
    prefix.length > 0
      ? all.filter((target) =>
          target.relative_directory.toLowerCase().startsWith(prefix),
        )
      : all
  const offset = query.cursor === null ? 0 : (parseTargetCursor(query.cursor) ?? 0)
  const items = filtered.slice(offset, offset + query.limit)
  const nextOffset = offset + query.limit
  return {
    items,
    next_cursor: nextOffset < filtered.length ? `t${nextOffset}` : null,
  }
}
