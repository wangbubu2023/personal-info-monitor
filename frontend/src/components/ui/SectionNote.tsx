import React from 'react'
import { InfoCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'

type SectionNoteTone = 'neutral' | 'caution'

interface SectionNoteProps {
  title?: React.ReactNode
  children: React.ReactNode
  tone?: SectionNoteTone
  style?: React.CSSProperties
}

const toneStyles: Record<SectionNoteTone, { background: string; border: string; accent: string; text: string }> = {
  neutral: {
    background: '#f6f3ea',
    border: '#ddd4bf',
    accent: '#6b7c3f',
    text: '#4f5643',
  },
  caution: {
    background: '#faf4e8',
    border: '#e6d0a8',
    accent: '#9a6d24',
    text: '#6a5330',
  },
}

const SectionNote: React.FC<SectionNoteProps> = ({
  title,
  children,
  tone = 'neutral',
  style,
}) => {
  const palette = toneStyles[tone]
  const Icon = tone === 'caution' ? ExclamationCircleOutlined : InfoCircleOutlined

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        padding: '12px 14px',
        borderRadius: 12,
        border: `1px solid ${palette.border}`,
        background: palette.background,
        color: palette.text,
        ...style,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 999,
          flex: '0 0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#fff',
          color: palette.accent,
          border: `1px solid ${palette.border}`,
          marginTop: 1,
        }}
      >
        <Icon />
      </div>
      <div style={{ minWidth: 0, lineHeight: 1.7 }}>
        {title ? (
          <div style={{ fontSize: 13, fontWeight: 600, color: '#2f3426', marginBottom: 2 }}>
            {title}
          </div>
        ) : null}
        <div style={{ fontSize: 13 }}>{children}</div>
      </div>
    </div>
  )
}

export default SectionNote
