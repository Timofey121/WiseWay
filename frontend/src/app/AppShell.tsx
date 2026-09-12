import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { roleLabel } from './roles'
import {
  appSections,
  defaultSectionId,
  notImplementedStatus,
  type AppSection,
  type AppSectionId,
} from './sections'
import { useAuthenticatedSession } from './use-session'

function SectionPlaceholder({ section }: { section: AppSection }) {
  const headingId = `section-${section.id}-heading`

  return (
    <section className="app-section ww-empty" aria-labelledby={headingId}>
      <div
        className="app-section__indicator ww-empty__indicator"
        aria-hidden="true"
      />
      <h2 id={headingId} className="app-section__heading">
        {section.label}
      </h2>
      <p className="app-section__status ww-badge ww-badge--info">
        {notImplementedStatus}
      </p>
      <p className="app-section__description">{section.description}</p>
    </section>
  )
}

/**
 * Русская оболочка приложения с навигацией по разделам.
 *
 * Активный раздел хранится только в состоянии React текущей вкладки: он не
 * пишется в URL, history state, browser storage или cookie. Переключение
 * раздела не выполняет сетевых запросов. До реализации входа стартовым
 * разделом всегда является «Поиск».
 *
 * `headerActions` — необязательный узел действий в шапке (например, доступное
 * управление выходом). Оболочка не знает о транспорте и не создаёт его.
 */
export interface AppShellProps {
  /** Действия в шапке справа; `undefined` — шапка без действий. */
  readonly headerActions?: ReactNode
}

export function AppShell({ headerActions }: AppShellProps = {}) {
  const [activeSectionId, setActiveSectionId] =
    useState<AppSectionId>(defaultSectionId)
  const session = useAuthenticatedSession()

  const activeSection = useMemo(
    () =>
      appSections.find((section) => section.id === activeSectionId) ??
      appSections[0],
    [activeSectionId],
  )

  const handleSelect = useCallback((sectionId: AppSectionId) => {
    setActiveSectionId(sectionId)
  }, [])

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div className="app-shell__header-row">
          <div className="app-shell__brand">
            <span className="app-shell__brand-mark" aria-hidden="true" />
            <div className="app-shell__brand-text">
              <h1 className="app-shell__title">WiseWay</h1>
              <p className="app-shell__subtitle">Поиск и сортировка файлов</p>
            </div>
          </div>
          {session || headerActions ? (
            <div className="app-shell__header-actions">
              {session ? (
                <div className="app-shell__user">
                  <span className="app-shell__user-name">
                    {session.actor.display_name}
                  </span>
                  <span className="app-shell__user-role ww-badge">
                    {roleLabel(session.actor.role)}
                  </span>
                </div>
              ) : null}
              {headerActions}
            </div>
          ) : null}
        </div>
      </header>

      <nav className="app-shell__nav" aria-label="Разделы приложения">
        <ul className="app-shell__nav-list">
          {appSections.map((section) => {
            const isActive = section.id === activeSectionId
            return (
              <li key={section.id} className="app-shell__nav-item">
                <button
                  type="button"
                  className="ww-nav__button app-shell__nav-button"
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => handleSelect(section.id)}
                >
                  {section.label}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      <main className="app-shell__content">
        <SectionPlaceholder section={activeSection} />
      </main>
    </div>
  )
}
