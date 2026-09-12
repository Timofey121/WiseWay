// Технический модуль scaffold: подтверждает, что alias-импорты JSON из
// `fixtures/synthetic/**` и `contracts/examples/**` (за пределами `frontend/`)
// разрешаются и в Vitest, и в dev-сервере Vite. Продуктовые данные не содержит.
import actorAdmin from '@examples/auth/actor-admin.json'
import manifest from '@fixtures/synthetic/manifest.json'

export { actorAdmin, manifest }
