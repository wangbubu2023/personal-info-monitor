import React from 'react'
import type { SourceType } from '../../types'

interface SourceIconProps {
  type: SourceType
  size?: 'small' | 'medium' | 'large'
  className?: string
}

const sizeClasses = {
  small: 'w-6 h-6',
  medium: 'w-10 h-10',
  large: 'w-16 h-16',
}

const iconSizes = {
  small: 'w-4 h-4',
  medium: 'w-6 h-6',
  large: 'w-10 h-10',
}

const SourceIcon: React.FC<SourceIconProps> = ({
  type,
  size = 'medium',
  className = '',
}) => {
  const renderIcon = () => {
    switch (type) {
      case 'website':
        return (
          <svg className={iconSizes[size]} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
          </svg>
        )
      case 'rss':
        return (
          <svg className={iconSizes[size]} viewBox="0 0 24 24" fill="currentColor">
            <path d="M6.18 17.82a1.64 1.64 0 110-3.28 1.64 1.64 0 010 3.28zm-1.64-8.1v2.34c3.99 0 7.23 3.24 7.23 7.23h2.34c0-5.28-4.29-9.57-9.57-9.57zm0-4.68v2.34c6.57 0 11.91 5.34 11.91 11.91h2.34c0-7.86-6.39-14.25-14.25-14.25z" />
          </svg>
        )
      case 'x':
        return (
          <svg className={iconSizes[size]} viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
          </svg>
        )
      case 'youtube':
        return (
          <svg className={iconSizes[size]} viewBox="0 0 24 24" fill="currentColor">
            <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
          </svg>
        )
      case 'podcast':
        return (
          <svg className={iconSizes[size]} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
          </svg>
        )
      default:
        return (
          <svg className={iconSizes[size]} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        )
    }
  }

  const colors: Record<SourceType, string> = {
    website: 'var(--color-type-website)',
    rss: '#d97706',
    x: 'var(--color-type-x)',
    youtube: 'var(--color-type-youtube)',
    podcast: 'var(--color-type-podcast)',
  }

  const bgColors: Record<SourceType, string> = {
    website: 'rgba(59, 130, 246, 0.1)',
    rss: 'rgba(217, 119, 6, 0.12)',
    x: 'rgba(20, 184, 166, 0.1)',
    youtube: 'rgba(239, 68, 68, 0.1)',
    podcast: 'rgba(168, 85, 247, 0.1)',
  }

  return (
    <div
      className={`${sizeClasses[size]} rounded-xl flex items-center justify-center ${className}`}
      style={{
        backgroundColor: bgColors[type],
        color: colors[type],
      }}
    >
      {renderIcon()}
    </div>
  )
}

export default SourceIcon
