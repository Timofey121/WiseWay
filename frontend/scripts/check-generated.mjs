// Проверка воспроизводимости generated-артефактов: перегенерация в временный
// каталог и сравнение с закоммиченными файлами. Любое расхождение — ошибка.
//
// Запуск: `npm run generate:api:check` из каталога `frontend/`.
// Этот скрипт — дополнительная автоматическая проверка к документированному
// `npm run generate:api` + `git diff --exit-code -- src/api/generated`.

import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { defaultOutputDir, generateApi } from './generate-api.mjs'

/** Приводит переводы строк к LF, чтобы core.autocrlf не давал ложный diff. */
function normalizeLineEndings(text) {
  return text.replace(/\r\n/g, '\n')
}

const ARTIFACTS = ['schema.ts', 'openapi.json']

const tempDir = await mkdtemp(path.join(os.tmpdir(), 'wiseway-generated-'))
let failed = false

try {
  await generateApi({ outputDir: tempDir })

  for (const artifact of ARTIFACTS) {
    const [actual, expected] = await Promise.all([
      readFile(path.join(tempDir, artifact), 'utf8'),
      readFile(path.join(defaultOutputDir, artifact), 'utf8'),
    ])

    if (normalizeLineEndings(actual) !== normalizeLineEndings(expected)) {
      failed = true
      console.error(
        `Расхождение после повторной генерации: ${path.join('src', 'api', 'generated', artifact)}`,
      )
    } else {
      console.log(`Без изменений: ${path.join('src', 'api', 'generated', artifact)}`)
    }
  }
} finally {
  await rm(tempDir, { recursive: true, force: true })
}

if (failed) {
  console.error(
    'Повторная генерация изменила generated-артефакты. Запустите `npm run generate:api` и закоммитьте результат.',
  )
  process.exit(1)
}

console.log('Generated-артефакты воспроизводимы без diff.')
