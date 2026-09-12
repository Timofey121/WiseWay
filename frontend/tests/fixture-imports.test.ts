import { describe, expect, it } from 'vitest'

import { actorAdmin, manifest } from './support/fixture-imports'

describe('импорт JSON вне каталога frontend', () => {
  it('читает синтетический корпус через alias @fixtures', () => {
    expect(manifest.fixture_set).toBe('wiseway-synthetic-metadata')
    expect(manifest.contract_version).toBe('1.0.0')
  })

  it('читает публичный пример контракта через alias @examples', () => {
    expect(actorAdmin.role).toBe('ADMIN')
    expect(actorAdmin.user_id).toBe('user-demo-admin-1')
  })
})
