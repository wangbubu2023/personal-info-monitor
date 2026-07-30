import React from 'react'

import InlineAnnotationChoices from './InlineAnnotationChoices'

export const LANE_CHOICES = [
  ['domestic_politics', '国内时政'],
  ['public_safety', '公共安全'],
  ['geopolitics', '地缘外交'],
  ['macro_economy', '宏观经济'],
  ['macro_finance', '宏观金融'],
  ['markets', '市场交易'],
  ['regulation', '监管政策'],
  ['industry_news', '行业新闻'],
  ['company_news', '公司新闻'],
  ['product_news', '产品新闻'],
  ['vc_deals', '创投融资'],
  ['public_figures', '公共人物'],
  ['other', '其它'],
].map(([value, label]) => ({ value, label }))

interface ContentInlineAnnotationProps {
  contentId: string
  title?: string
  summary?: string
  predictedLane?: string | null
  compact?: boolean
}

const ContentInlineAnnotation: React.FC<ContentInlineAnnotationProps> = ({
  contentId,
  title,
  summary,
  predictedLane,
  compact = false,
}) => {
  const context = { title, summary: summary?.slice(0, 1200) }
  const prediction = predictedLane ? { lane: predictedLane } : {}

  if (compact) {
    return (
      <InlineAnnotationChoices
        taskType="content_value"
        targetType="content"
        targetId={contentId}
        label="顺手标"
        compact
        loadExisting={false}
        context={context}
        prediction={prediction}
        choices={[
          { value: 'must_see', label: '必看' },
          { value: 'ok', label: '一般' },
          { value: 'noise', label: '噪音' },
        ]}
      />
    )
  }

  return (
    <section className="rounded-2xl border border-[#49A8C9]/15 bg-[#f7fbfd] p-4" data-testid="content-inline-annotation">
      <div className="mb-3">
        <h2 className="text-[14px] font-semibold text-[#293859]">阅读时顺手标一下</h2>
        <p className="mt-1 text-[11px] text-[#8a96a5]">每项点击即保存；不确定可以留空。</p>
      </div>
      <div className="space-y-4">
        <InlineAnnotationChoices
          taskType="content_value"
          targetType="content"
          targetId={contentId}
          label="对你是否值得看"
          context={context}
          prediction={prediction}
          choices={[
            { value: 'must_see', label: '必看' },
            { value: 'ok', label: '一般' },
            { value: 'noise', label: '噪音' },
          ]}
        />
        <InlineAnnotationChoices
          taskType="content_quality"
          targetType="content"
          targetId={contentId}
          label="内容质量"
          context={context}
          choices={[
            { value: 'high', label: '高' },
            { value: 'medium', label: '中' },
            { value: 'low', label: '低' },
            { value: 'unclear', label: '不确定' },
          ]}
        />
        <InlineAnnotationChoices
          taskType="content_fact_density"
          targetType="content"
          targetId={contentId}
          label="事实密度"
          context={context}
          choices={[
            { value: 'dense', label: '密集' },
            { value: 'moderate', label: '适中' },
            { value: 'sparse', label: '稀少' },
            { value: 'unclear', label: '不确定' },
          ]}
        />
        <details className="group">
          <summary className="cursor-pointer text-[12px] font-semibold text-[#3a8da9]">分类不对？修正 Lane</summary>
          <div className="mt-3">
            <InlineAnnotationChoices
              taskType="content_lane"
              targetType="content"
              targetId={contentId}
              label="正确分类"
              context={context}
              prediction={prediction}
              choices={LANE_CHOICES}
            />
          </div>
        </details>
      </div>
    </section>
  )
}

export default ContentInlineAnnotation
