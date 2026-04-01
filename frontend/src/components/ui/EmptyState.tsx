import React from 'react'

interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
}

const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  action,
}) => {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      {icon && (
        <div className="w-16 h-16 rounded-full bg-[var(--color-surface-hover)] flex items-center justify-center mb-4 text-[var(--color-text-tertiary)]">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-medium text-[var(--color-text)] mb-2">
        {title}
      </h3>
      {description && (
        <p className="text-[var(--color-text-secondary)] text-center max-w-sm mb-4">
          {description}
        </p>
      )}
      {action}
    </div>
  )
}

export default EmptyState
