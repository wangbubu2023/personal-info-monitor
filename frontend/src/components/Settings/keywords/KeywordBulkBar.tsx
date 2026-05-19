import React from 'react'
import { Button, Select, Space } from 'antd'

import type { KeywordMatchScope, MatchType } from '../../../types'
import { matchScopeLabels, matchTypeLabels } from './keywordConstants'
import KeywordColorSwatches from './KeywordColorSwatches'

export type KeywordBulkBarProps = {
  selectedCount: number
  color?: string
  matchScope?: KeywordMatchScope
  matchType?: MatchType
  enabled?: boolean
  isApplying: boolean
  onColorChange: (value: string | undefined) => void
  onMatchScopeChange: (value: KeywordMatchScope | undefined) => void
  onMatchTypeChange: (value: MatchType | undefined) => void
  onEnabledChange: (value: boolean | undefined) => void
  onClear: () => void
  onApply: () => void
}

const KeywordBulkBar: React.FC<KeywordBulkBarProps> = ({
  selectedCount,
  color,
  matchScope,
  matchType,
  enabled,
  isApplying,
  onColorChange,
  onMatchScopeChange,
  onMatchTypeChange,
  onEnabledChange,
  onClear,
  onApply,
}) => {
  if (selectedCount <= 0) return null
  return (
    <div className="mb-4 flex flex-col gap-3 rounded-xl border border-[#49A8C9]/18 bg-[#f7fbfd] px-4 py-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        <div className="text-[13px] font-semibold text-[#2c3a50]">已选中 {selectedCount} 个关键词</div>
        <div className="text-[12px] text-[#6d7c8d]">可批量修改颜色、生效范围、匹配类型与启用状态。</div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div>
          <div className="mb-1 text-[12px] font-medium text-[#586476]">标签颜色</div>
          <KeywordColorSwatches size="compact" value={color} onChange={onColorChange} />
        </div>
        <div className="min-w-[10rem]">
          <div className="mb-1 text-[12px] font-medium text-[#586476]">生效范围</div>
          <Select<KeywordMatchScope>
            allowClear
            placeholder="选择范围"
            value={matchScope}
            onChange={(value) => onMatchScopeChange(value)}
            options={Object.entries(matchScopeLabels).map(([value, label]) => ({ value: value as KeywordMatchScope, label }))}
          />
        </div>
        <div className="min-w-[10rem]">
          <div className="mb-1 text-[12px] font-medium text-[#586476]">匹配类型</div>
          <Select<MatchType>
            allowClear
            placeholder="匹配类型"
            value={matchType}
            onChange={(value) => onMatchTypeChange(value)}
            options={(Object.keys(matchTypeLabels) as MatchType[]).map((value) => ({ value, label: matchTypeLabels[value] }))}
          />
        </div>
        <div className="min-w-[10rem]">
          <div className="mb-1 text-[12px] font-medium text-[#586476]">状态</div>
          <Select<boolean>
            allowClear
            placeholder="启用 / 禁用"
            value={enabled}
            onChange={(value) => onEnabledChange(value ?? undefined)}
          >
            <Select.Option value={true}>启用</Select.Option>
            <Select.Option value={false}>禁用</Select.Option>
          </Select>
        </div>
        <Space>
          <Button onClick={onClear}>清空选择</Button>
          <Button type="primary" onClick={onApply} loading={isApplying}>
            应用到已选
          </Button>
        </Space>
      </div>
    </div>
  )
}

export default KeywordBulkBar
