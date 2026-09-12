// Русские пользовательские подписи роли актора.
//
// Роль приходит из публичного контракта как машинное значение `WORKER|ADMIN` и
// остаётся в state/transport без изменений. Перевод выполняется только на
// границе показа (D-07): `roleLabel()` — единственное место, где enum
// превращается в русскую подпись.

import type { components } from '@/api/generated/schema'

/** Машинное значение роли из `#/components/schemas/Actor.role`. */
export type UserRole = components['schemas']['Actor']['role']

const ROLE_LABELS: Record<UserRole, string> = {
  WORKER: 'Рабочий',
  ADMIN: 'Администратор',
}

/** Русская подпись роли для показа пользователю. */
export function roleLabel(role: UserRole): string {
  return ROLE_LABELS[role]
}
