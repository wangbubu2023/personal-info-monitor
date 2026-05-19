import React from 'react'

import { KEYWORD_LABEL_COLORS, type KeywordLabelColor } from './keywordConstants'

export type KeywordColorSwatchesProps = {
  value?: string
  onChange?: (hex: KeywordLabelColor) => void
  size?: 'default' | 'compact'
}

const KeywordColorSwatches: React.FC<KeywordColorSwatchesProps> = ({ value, onChange, size = 'default' }) => {
  const btn = size === 'compact' ? 'h-7 w-7 min-h-[1.75rem] min-w-[1.75rem]' : 'h-9 w-9 min-h-9 min-w-9'
  return (
    <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="标签颜色">
      {KEYWORD_LABEL_COLORS.map((hex) => {
        const selected = value === hex
        return (
          <button
            key={hex}
            type="button"
            role="radio"
            aria-checked={selected}
            title={hex}
            className={`${btn} shrink-0 rounded-lg border-2 transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-[#49A8C9]/80 ${
              selected
                ? 'border-[#2c3a50] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.35)]'
                : 'border-white/90 shadow-sm hover:border-[#b8c4d0]'
            }`}
            style={{ backgroundColor: hex }}
            onClick={() => onChange?.(hex)}
          />
        )
      })}
    </div>
  )
}

export default KeywordColorSwatches
