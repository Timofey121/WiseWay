// Воспроизводимая генерация артефактов из единственного публичного OAS.
//
// Источник: `contracts/openapi/wiseway-v1.yaml` (OpenAPI 3.1.1, version 1.0.0).
// Результат:
//   - `src/api/generated/schema.ts`        — TypeScript-типы (openapi-typescript 7);
//   - `src/api/generated/openapi.json`     — машинно-читаемый JSON OAS для runtime-mocks;
//   - `src/api/generated/operation-meta.ts` — карта `METHOD path` → metadata операции
//     (operationId, требуется ли CSRF, требуется ли Idempotency-Key), выведенная из OAS.
//
// Файлы генерируются целиком и не редактируются вручную. Скрипт идемпотентен:
// повторный запуск при неизменном OAS не меняет ни один артефакт.

import { spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse as parseYaml } from 'yaml'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** Путь к единственному публичному контракту. */
export const oasPath = path.resolve(
  frontendDir,
  '..',
  'contracts',
  'openapi',
  'wiseway-v1.yaml',
)

/** Каталог generated-артефактов по умолчанию. */
export const defaultOutputDir = path.join(frontendDir, 'src', 'api', 'generated')

const openapiTypescriptCli = path.join(
  frontendDir,
  'node_modules',
  'openapi-typescript',
  'bin',
  'cli.js',
)

/** Порядок HTTP-методов для детерминированной генерации operation-meta. */
const HTTP_METHODS = [
  'get',
  'put',
  'post',
  'delete',
  'options',
  'head',
  'patch',
  'trace',
]

/** Точные `$ref`, наличие которых объявляет CSRF/идемпотентность операции. */
const CSRF_PARAMETER_REF = '#/components/parameters/XCSRFToken'
const IDEMPOTENCY_PARAMETER_REF = '#/components/parameters/IdempotencyKey'

/**
 * Проверяет, ссылается ли операция (или её path item) на общий параметр.
 *
 * @param {Record<string, unknown>} operation
 * @param {Record<string, unknown>} pathItem
 * @param {string} ref
 * @returns {boolean}
 */
function referencesParameter(operation, pathItem, ref) {
  const parameters = [
    ...(Array.isArray(pathItem.parameters) ? pathItem.parameters : []),
    ...(Array.isArray(operation.parameters) ? operation.parameters : []),
  ]
  return parameters.some((parameter) => parameter && parameter.$ref === ref)
}

/**
 * Строит детерминированный список metadata всех операций OAS.
 *
 * @param {Record<string, unknown>} document
 * @returns {{ method: string, path: string, operationId: string, csrf: boolean, idempotencyKey: boolean }[]}
 */
export function buildOperationMeta(document) {
  const entries = []
  for (const [pathKey, pathItem] of Object.entries(document.paths ?? {})) {
    for (const method of HTTP_METHODS) {
      const operation = pathItem[method]
      if (!operation || typeof operation !== 'object') continue
      entries.push({
        method: method.toUpperCase(),
        path: pathKey,
        operationId: String(operation.operationId ?? ''),
        csrf: referencesParameter(operation, pathItem, CSRF_PARAMETER_REF),
        idempotencyKey: referencesParameter(
          operation,
          pathItem,
          IDEMPOTENCY_PARAMETER_REF,
        ),
      })
    }
  }
  return entries
}

/**
 * Рендерит `operation-meta.ts` с картой `METHOD path` → metadata.
 *
 * @param {{ method: string, path: string, operationId: string, csrf: boolean, idempotencyKey: boolean }[]} entries
 * @returns {string}
 */
export function renderOperationMeta(entries) {
  const lines = [
    '// Этот файл сгенерирован scripts/generate-api.mjs из',
    '// contracts/openapi/wiseway-v1.yaml. Не редактируется вручную: изменения',
    '// будут перезаписаны следующей генерацией `npm run generate:api`.',
    '//',
    '// `csrf`/`idempotencyKey` выведены из наличия `$ref` на',
    '// #/components/parameters/XCSRFToken и #/components/parameters/IdempotencyKey.',
    '',
    'export interface OperationMeta {',
    '  /** operationId операции в публичном OAS. */',
    '  operationId: string',
    '  /** Требует ли операция заголовок X-CSRF-Token. */',
    '  csrf: boolean',
    '  /** Требует ли операция заголовок Idempotency-Key. */',
    '  idempotencyKey: boolean',
    '}',
    '',
    'export const operationMeta = {',
  ]
  for (const entry of entries) {
    lines.push(
      `  '${entry.method} ${entry.path}': { operationId: '${entry.operationId}', csrf: ${entry.csrf}, idempotencyKey: ${entry.idempotencyKey} },`,
    )
  }
  lines.push(
    '} as const satisfies Record<string, OperationMeta>',
    '',
    'export type OperationMetaKey = keyof typeof operationMeta',
    '',
  )
  return lines.join('\n')
}

/**
 * Генерирует `schema.ts`, `openapi.json` и `operation-meta.ts` из OAS.
 *
 * @param {{ outputDir?: string }} [options]
 * @returns {Promise<{ schemaPath: string, jsonPath: string, operationMetaPath: string }>}
 */
export async function generateApi({ outputDir = defaultOutputDir } = {}) {
  await mkdir(outputDir, { recursive: true })

  const schemaPath = path.join(outputDir, 'schema.ts')
  const jsonPath = path.join(outputDir, 'openapi.json')
  const operationMetaPath = path.join(outputDir, 'operation-meta.ts')

  const result = spawnSync(
    process.execPath,
    [openapiTypescriptCli, oasPath, '-o', schemaPath],
    { stdio: 'inherit' },
  )
  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    throw new Error(
      `openapi-typescript завершился с кодом ${result.status ?? 'unknown'}`,
    )
  }

  const source = await readFile(oasPath, 'utf8')
  const document = parseYaml(source)
  await writeFile(jsonPath, `${JSON.stringify(document, null, 2)}\n`, 'utf8')
  await writeFile(
    operationMetaPath,
    renderOperationMeta(buildOperationMeta(document)),
    'utf8',
  )

  return { schemaPath, jsonPath, operationMetaPath }
}

const isDirectRun =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isDirectRun) {
  const { schemaPath, jsonPath, operationMetaPath } = await generateApi()
  console.log(`Сгенерировано: ${schemaPath}`)
  console.log(`Сгенерировано: ${jsonPath}`)
  console.log(`Сгенерировано: ${operationMetaPath}`)
}
