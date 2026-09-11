// Воспроизводимая генерация артефактов из единственного публичного OAS.
//
// Источник: `contracts/openapi/wiseway-v1.yaml` (OpenAPI 3.1.1, version 1.0.0).
// Результат:
//   - `src/api/generated/schema.ts`   — TypeScript-типы (openapi-typescript 7);
//   - `src/api/generated/openapi.json` — машинно-читаемый JSON OAS для runtime-mocks.
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

/**
 * Генерирует `schema.ts` и `openapi.json` из OAS в указанный каталог.
 *
 * @param {{ outputDir?: string }} [options]
 * @returns {Promise<{ schemaPath: string, jsonPath: string }>}
 */
export async function generateApi({ outputDir = defaultOutputDir } = {}) {
  await mkdir(outputDir, { recursive: true })

  const schemaPath = path.join(outputDir, 'schema.ts')
  const jsonPath = path.join(outputDir, 'openapi.json')

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

  return { schemaPath, jsonPath }
}

const isDirectRun =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isDirectRun) {
  const { schemaPath, jsonPath } = await generateApi()
  console.log(`Сгенерировано: ${schemaPath}`)
  console.log(`Сгенерировано: ${jsonPath}`)
}
