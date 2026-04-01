import React from 'react'
import { KEYWORD_MONITORING_ENABLED } from '../../config/features'
import type { DigestItem } from '../../types'

interface DashboardItemCardProps {
  item: DigestItem
  timeText: string
  translationAction?: React.ReactNode
}

const DashboardItemCard: React.FC<DashboardItemCardProps> = ({ item, timeText, translationAction }) => (
  <article
    key={item.id}
    data-testid={`dashboard-item-${item.id}`}
    style={{
      padding: '20px 0',
      borderBottom: '1px solid #f0f0f0',
    }}
  >
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      marginBottom: 8,
    }}>
      <span style={{
        fontSize: 13,
        color: '#6b7c3f',
        fontWeight: 500,
      }}>
        {item.source_name}
      </span>
      <span style={{
        fontSize: 12,
        color: '#999',
      }}>
        {timeText}
      </span>
      {item.read_status && (
        <span style={{
          fontSize: 11,
          color: '#999',
          backgroundColor: '#f5f5f5',
          padding: '1px 6px',
          borderRadius: 3,
        }}>
          已读
        </span>
      )}
    </div>

    <h2 style={{
      fontSize: 17,
      fontWeight: 500,
      color: item.read_status ? '#999' : '#333',
      margin: '0 0 8px',
      lineHeight: 1.5,
    }}>
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: 'inherit',
          textDecoration: 'none',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = '#6b7c3f'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = item.read_status ? '#999' : '#333'
        }}
      >
        {item.translated_title || item.title}
      </a>
      {translationAction}
    </h2>

    {(item.translated_summary || item.summary) && (
      <p style={{
        fontSize: 14,
        color: '#666',
        lineHeight: 1.7,
        margin: 0,
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {item.translated_summary || item.summary}
      </p>
    )}
    {KEYWORD_MONITORING_ENABLED && item.keyword_matches?.length > 0 && (
      <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {item.keyword_matches.map((kw) => (
          <span key={kw.id} style={{
            fontSize: 11,
            padding: '2px 8px',
            backgroundColor: `${kw.color || '#ff4d4f'}15`,
            color: kw.color || '#ff4d4f',
            borderRadius: 3,
          }}>
            {kw.keyword}
          </span>
        ))}
      </div>
    )}
  </article>
)

export default DashboardItemCard
