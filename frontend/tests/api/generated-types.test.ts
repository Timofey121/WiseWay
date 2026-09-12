import { describe, expectTypeOf, it } from 'vitest'

import type { components, operations, paths } from '@/api/generated/schema'

// Type-level проверки generated-схемы. `expectTypeOf` не выполняет проверок во
// время исполнения: утверждения проверяет `tsc` (npm run typecheck), а сам файл
// запускается Vitest как обычный (пустой) тест.
type Schemas = components['schemas']

describe('generated-типы из публичного OAS', () => {
  it('типизирует тело login как {login, password}', () => {
    expectTypeOf<Schemas['LoginRequest']>().toEqualTypeOf<{
      login: string
      password: string
    }>()
    expectTypeOf<
      paths['/auth/login']['post']['requestBody']['content']['application/json']
    >().toEqualTypeOf<{ login: string; password: string }>()
    expectTypeOf<
      operations['login']['requestBody']['content']['application/json']
    >().toEqualTypeOf<Schemas['LoginRequest']>()
  })

  it('SelectionRequest — union EXPLICIT | ALL_MATCHING', () => {
    expectTypeOf<
      Schemas['ExplicitSelectionRequest']
    >().toExtend<Schemas['SelectionRequest']>()
    expectTypeOf<
      Schemas['AllMatchingSelectionRequest']
    >().toExtend<Schemas['SelectionRequest']>()
    expectTypeOf<Schemas['SelectionRequest']>().toEqualTypeOf<
      Schemas['ExplicitSelectionRequest'] | Schemas['AllMatchingSelectionRequest']
    >()
    expectTypeOf<
      Schemas['ExplicitSelectionRequest']['mode']
    >().toEqualTypeOf<'EXPLICIT'>()
    expectTypeOf<
      Schemas['AllMatchingSelectionRequest']['mode']
    >().toEqualTypeOf<'ALL_MATCHING'>()
  })

  it('BatchCreateRequest — union DIRECT | PREVIEWED', () => {
    expectTypeOf<
      Schemas['DirectBatchCreateRequest']
    >().toExtend<Schemas['BatchCreateRequest']>()
    expectTypeOf<
      Schemas['PreviewedBatchCreateRequest']
    >().toExtend<Schemas['BatchCreateRequest']>()
    expectTypeOf<Schemas['BatchCreateRequest']>().toEqualTypeOf<
      Schemas['DirectBatchCreateRequest'] | Schemas['PreviewedBatchCreateRequest']
    >()
    expectTypeOf<
      Schemas['DirectBatchCreateRequest']['execution_mode']
    >().toEqualTypeOf<'DIRECT'>()
    expectTypeOf<
      Schemas['PreviewedBatchCreateRequest']['execution_mode']
    >().toEqualTypeOf<'PREVIEWED'>()
    expectTypeOf<
      Schemas['PreviewedBatchCreateRequest']['preview_id']
    >().toEqualTypeOf<string>()
  })

  it('SearchRequest/SearchResponse сохраняют nullable-поля', () => {
    expectTypeOf<Schemas['SearchRequest']['query_text']>().toEqualTypeOf<string>()
    expectTypeOf<
      Schemas['SearchRequest']['selected_marker_ids']
    >().toEqualTypeOf<string[]>()
    expectTypeOf<Schemas['SearchResponse']['total']>().toEqualTypeOf<
      number | null
    >()
    expectTypeOf<Schemas['SearchResponse']['next_facet']>().toEqualTypeOf<
      Schemas['Facet'] | null
    >()
  })

  it('страничные ответы имеют nullable next_cursor', () => {
    expectTypeOf<Schemas['Simulation']['next_cursor']>().toEqualTypeOf<
      string | null
    >()
    expectTypeOf<Schemas['BatchPage']['next_cursor']>().toEqualTypeOf<
      string | null
    >()
    expectTypeOf<Schemas['QuarantinePage']['next_cursor']>().toEqualTypeOf<
      string | null
    >()
    expectTypeOf<Schemas['PageTargetDirectory']['next_cursor']>().toEqualTypeOf<
      string | null
    >()
  })

  it('ErrorDetails несёт request_id/operation_id/field_errors', () => {
    expectTypeOf<Schemas['ErrorDetails']['request_id']>().toEqualTypeOf<string>()
    expectTypeOf<Schemas['ErrorDetails']['operation_id']>().toEqualTypeOf<
      string | null
    >()
    expectTypeOf<Schemas['ErrorDetails']['field_errors']>().toEqualTypeOf<
      Schemas['FieldError'][]
    >()
    expectTypeOf<Schemas['FieldError']['field']>().toEqualTypeOf<string>()
  })

  it('GET-списки требуют query company_id', () => {
    expectTypeOf<
      operations['listSortingBatches']['parameters']['query']['company_id']
    >().toEqualTypeOf<string>()
    expectTypeOf<
      operations['listQuarantineItems']['parameters']['query']['company_id']
    >().toEqualTypeOf<string>()
  })

  it('мутации объявляют заголовки X-CSRF-Token и Idempotency-Key', () => {
    expectTypeOf<
      operations['createSortingBatch']['parameters']['header']['X-CSRF-Token']
    >().toEqualTypeOf<string>()
    expectTypeOf<
      operations['createSortingBatch']['parameters']['header']['Idempotency-Key']
    >().toEqualTypeOf<string>()
    expectTypeOf<
      operations['publishDictionary']['parameters']['header']['Idempotency-Key']
    >().toEqualTypeOf<string>()
    expectTypeOf<
      operations['logout']['parameters']['header']['X-CSRF-Token']
    >().toEqualTypeOf<string>()
  })

  it('paths связаны с operations', () => {
    expectTypeOf<paths['/auth/login']['post']>().toEqualTypeOf<
      operations['login']
    >()
  })
})
