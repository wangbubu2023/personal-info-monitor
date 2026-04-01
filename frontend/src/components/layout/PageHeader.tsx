import React from 'react'
import { Link } from 'react-router-dom'

interface Breadcrumb {
  label: string
  path?: string
}

interface PageHeaderProps {
  title: string
  description?: string
  breadcrumbs?: Breadcrumb[]
  action?: React.ReactNode
}

const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  breadcrumbs,
  action,
}) => {
  return (
    <div className="mb-8">
      {/* Breadcrumbs */}
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav className="flex items-center gap-2 text-sm text-[var(--color-text-tertiary)] mb-4">
          <Link to="/" className="hover:text-[var(--color-primary)]">
            首页
          </Link>
          {breadcrumbs.map((crumb, index) => (
            <React.Fragment key={index}>
              <span className="text-[var(--color-border)]">/</span>
              {crumb.path ? (
                <Link to={crumb.path} className="hover:text-[var(--color-primary)]">
                  {crumb.label}
                </Link>
              ) : (
                <span className="text-[var(--color-text-secondary)]">{crumb.label}</span>
              )}
            </React.Fragment>
          ))}
        </nav>
      )}

      {/* Title and Action */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-[var(--color-text)] mb-2">
            {title}
          </h1>
          {description && (
            <p className="text-[var(--color-text-secondary)] text-lg max-w-2xl">
              {description}
            </p>
          )}
        </div>
        {action && (
          <div className="flex-shrink-0">
            {action}
          </div>
        )}
      </div>
    </div>
  )
}

export default PageHeader
