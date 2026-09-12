// Runtime-валидация mock-запросов по схемам единственного публичного OAS.
//
// OAS 3.1 `components.schemas` — это JSON Schema 2020-12, поэтому валидация
// выполняется `ajv@8` (`ajv/dist/2020`) с `ajv-formats`. Весь generated OAS
// (`@/api/generated/openapi.json`) регистрируется как один schema-документ под
// стабильным `$id`; `$ref: '#/components/schemas/...'` внутри него резолвится
// без ручного копирования схем.
//
// Валидация не подменяет собой контракт: `additionalProperties: false`,
// `required`, `minLength`, enum и прочие ограничения берутся из OAS. Невалидный
// payload отклоняется до вызова handler-успеха.

import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020'
import addFormats from 'ajv-formats'

import openapi from '@/api/generated/openapi.json'

import type { FieldError } from './types'

const OAS_SCHEMA_ID = 'https://wiseway.local/openapi.json'
const JSON_SCHEMA_2020_12 = 'https://json-schema.org/draft/2020-12/schema'

let ajvInstance: Ajv2020 | null = null
const validatorCache = new Map<string, ValidateFunction>()

function getAjv(): Ajv2020 {
  if (!ajvInstance) {
    const instance = new Ajv2020({
      strict: false,
      allErrors: true,
      allowUnionTypes: true,
    })
    addFormats(instance)
    instance.addSchema({
      ...(openapi as Record<string, unknown>),
      $id: OAS_SCHEMA_ID,
      $schema: JSON_SCHEMA_2020_12,
    })
    ajvInstance = instance
  }
  return ajvInstance
}

/** Компилирует (с кэшем) валидатор схемы по её имени в `components.schemas`. */
export function getSchemaValidator(schemaName: string): ValidateFunction {
  const cached = validatorCache.get(schemaName)
  if (cached) {
    return cached
  }
  const validate = getAjv().getSchema(
    `${OAS_SCHEMA_ID}#/components/schemas/${schemaName}`,
  )
  if (!validate) {
    throw new Error(`Схема "${schemaName}" отсутствует в generated OAS`)
  }
  validatorCache.set(schemaName, validate)
  return validate
}

export interface SchemaValidationResult {
  valid: boolean
  errors: ErrorObject[]
}

/** Валидирует значение против именованной схемы `components.schemas`. */
export function validateSchema(
  schemaName: string,
  value: unknown,
): SchemaValidationResult {
  const validate = getSchemaValidator(schemaName)
  const valid = validate(value) === true
  return { valid, errors: valid ? [] : (validate.errors ?? []) }
}

/** Безопасное русское сообщение по ключевому слову JSON Schema. */
function messageForKeyword(keyword: string): string {
  switch (keyword) {
    case 'required':
      return 'Обязательное поле.'
    case 'additionalProperties':
      return 'Неизвестное поле запроса.'
    case 'minLength':
      return 'Значение слишком короткое.'
    case 'maxLength':
      return 'Значение слишком длинное.'
    case 'type':
      return 'Неверный тип значения.'
    case 'enum':
      return 'Недопустимое значение поля.'
    default:
      return 'Недопустимое значение поля.'
  }
}

/** Технический код поля по ключевому слову JSON Schema (не переводится). */
function codeForKeyword(keyword: string): string {
  switch (keyword) {
    case 'additionalProperties':
      return 'ADDITIONAL_PROPERTY'
    case 'minLength':
      return 'MIN_LENGTH'
    case 'maxLength':
      return 'MAX_LENGTH'
    default:
      return keyword.toUpperCase()
  }
}

function fieldNameFromError(error: ErrorObject): string {
  if (
    error.keyword === 'required' &&
    typeof error.params === 'object' &&
    error.params !== null &&
    'missingProperty' in error.params
  ) {
    return String((error.params as { missingProperty: unknown }).missingProperty)
  }
  if (
    error.keyword === 'additionalProperties' &&
    typeof error.params === 'object' &&
    error.params !== null &&
    'additionalProperty' in error.params
  ) {
    return String(
      (error.params as { additionalProperty: unknown }).additionalProperty,
    )
  }
  const path = error.instancePath.replace(/^\//, '').replace(/\//g, '.')
  return path.length > 0 ? path : 'request'
}

/**
 * Преобразует ошибки ajv в безопасные `FieldError` контракта. Значения полей и
 * тела запроса не эхо-тся: только имя поля, технический код и русское
 * сообщение.
 */
export function toFieldErrors(errors: ErrorObject[]): FieldError[] {
  const seen = new Set<string>()
  const result: FieldError[] = []
  for (const error of errors) {
    const field = fieldNameFromError(error)
    const code = codeForKeyword(error.keyword)
    const key = `${field}:${code}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push({ field, code, message: messageForKeyword(error.keyword) })
  }
  return result
}
