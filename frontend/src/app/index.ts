// Оболочка WiseWay: единая русская навигация по разделам и честные заглушки
// ещё не реализованных экранов. Активный раздел живёт только в памяти вкладки.

export { AppShell } from './AppShell'
export {
  appSections,
  defaultSectionId,
  notImplementedStatus,
  type AppSection,
  type AppSectionId,
} from './sections'
export {
  registerPrivateStateReset,
  resetPrivateState,
  type PrivateStateReset,
} from './private-state-registry'
