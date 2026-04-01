import React from 'react'
import type { SourceType } from '../../types'

interface BadgeProps {
  children: React.ReactNode
  type?: SourceType | 'default'
  className?: string
}

const typeStyles: Record<string, { bg: string; text: string }> = {
  website: { bg: 'rgba(59, 130, 246, 0.1)', text: 'var(--color-type-website)' },
  x: { bg: 'rgba(20, 184, 166, 0.1)', text: 'var(--color-type-x)' },
  youtube: { bg: 'rgba(239, 68, 68, 0.1)', text: 'var(--color-type-youtube)' },
  podcast: { bg: 'rgba(168, 85, 247, 0.1)', text: 'var(--color-type-podcast)' },
  default: { bg: 'var(--color-surface-hover)', text: 'var(--color-text-secondary)' },
}

const Badge: React.FC<BadgeProps> = ({
  children,
  type = 'default',
  className = '',
}) => {
  const styles = typeStyles[type] || typeStyles.default

  return (
    <span
      className={`
        inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-medium
        ${className}
      `}
      style={{
        backgroundColor: styles.bg,
        color: styles.text,
      }}
    >
      {children}
    </span>
  )
}

export default Badge
