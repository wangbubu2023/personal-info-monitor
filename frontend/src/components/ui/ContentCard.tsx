import React from 'react'
import { StarFilled, StarOutlined } from '@ant-design/icons'
import { KEYWORD_MONITORING_ENABLED } from '../../config/features'
import Badge from './Badge'
import SourceIcon from './SourceIcon'
import type { SourceType } from '../../types'
import { formatLocalDate } from '../../utils/datetime'

interface ContentCardProps {
  id: string
  title: string
  translatedTitle?: string
  summary?: string
  translatedSummary?: string
  url: string
  sourceName: string
  sourceType: SourceType
  publishTime?: string
  isRead?: boolean
  isFavorited?: boolean
  keywords?: Array<{ id: string; keyword: string; color?: string }>
  onFavoriteToggle?: (id: string) => void
  onMarkAsRead?: (id: string) => void
}

const ContentCard: React.FC<ContentCardProps> = ({
  id,
  title,
  translatedTitle,
  summary,
  translatedSummary,
  url,
  sourceName,
  sourceType,
  publishTime,
  isRead = false,
  isFavorited = false,
  keywords = [],
  onFavoriteToggle,
  onMarkAsRead,
}) => {
  const displayTitle = translatedTitle || title
  const displaySummary = translatedSummary || summary

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return ''
    return formatLocalDate(dateStr, 'zh-CN', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  const handleClick = () => {
    if (!isRead && onMarkAsRead) {
      onMarkAsRead(id)
    }
  }

  return (
    <div 
      className={`
        bg-white rounded-xl overflow-hidden border border-[var(--color-border-light)]
        transition-all duration-200 hover:shadow-lg hover:border-[var(--color-border)]
        ${isRead ? 'opacity-75' : ''}
      `}
    >
      {/* Card Header - Source Icon Area */}
      <div className="aspect-[16/9] bg-gradient-to-br from-gray-50 to-gray-100 flex items-center justify-center relative">
        <SourceIcon type={sourceType} size="large" />
        
        {/* Favorite Button */}
        <button
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onFavoriteToggle?.(id)
          }}
          className={`
            absolute top-3 right-3 p-2 rounded-full transition-all
            ${isFavorited 
              ? 'bg-yellow-50 text-yellow-500' 
              : 'bg-white/80 text-gray-400 hover:text-yellow-500 hover:bg-white'
            }
          `}
        >
          {isFavorited ? <StarFilled /> : <StarOutlined />}
        </button>

        {/* Read Status */}
        {isRead && (
          <div className="absolute top-3 left-3">
            <span className="text-xs bg-gray-200 text-gray-600 px-2 py-1 rounded-full">
              已读
            </span>
          </div>
        )}
      </div>

      {/* Card Content */}
      <div className="p-4">
        {/* Meta Info */}
        <div className="flex items-center gap-2 text-sm mb-3">
          <Badge type={sourceType}>{sourceName}</Badge>
          {publishTime && (
            <>
              <span className="text-[var(--color-text-tertiary)]">/</span>
              <span className="text-[var(--color-text-tertiary)]">
                {formatDate(publishTime)}
              </span>
            </>
          )}
        </div>

        {/* Title */}
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="block group"
        >
          <h3 className="font-semibold text-lg text-[var(--color-text)] mb-2 line-clamp-2 group-hover:text-[var(--color-primary)] transition-colors">
            {displayTitle}
          </h3>
        </a>

        {/* Summary */}
        {displaySummary && (
          <p className="text-[var(--color-text-secondary)] text-sm line-clamp-3 mb-3">
            {displaySummary}
          </p>
        )}

        {/* Keywords */}
        {KEYWORD_MONITORING_ENABLED && keywords.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {keywords.map((kw) => (
              <span
                key={kw.id}
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: `${kw.color || '#ff4d4f'}15`,
                  color: kw.color || '#ff4d4f',
                }}
              >
                {kw.keyword}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ContentCard
