import React from 'react'

import InlineAnnotationChoices from './InlineAnnotationChoices'

interface ContentInlineAnnotationProps {
  contentId: string
  title?: string
  summary?: string
}

const ContentInlineAnnotation: React.FC<ContentInlineAnnotationProps> = ({
  contentId,
  title,
  summary,
}) => {
  const context = { title, summary: summary?.slice(0, 1200) }

  return (
    <section className="rounded-2xl border border-[#49A8C9]/15 bg-[#f7fbfd] p-4" data-testid="content-inline-annotation">
      <div className="mb-3">
        <h2 className="text-[14px] font-semibold text-[#293859]">内容反馈</h2>
        <p className="mt-1 text-[11px] text-[#8a96a5]">对正文内容与呈现质量的判断，点击即保存。</p>
      </div>
      <div className="space-y-4">
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
          ]}
        />
        <InlineAnnotationChoices
          taskType="content_format_quality"
          targetType="content"
          targetId={contentId}
          label="格式质量"
          context={context}
          choices={[
            { value: 'high', label: '高' },
            { value: 'medium', label: '中' },
            { value: 'low', label: '低' },
          ]}
        />
      </div>
    </section>
  )
}

export default ContentInlineAnnotation
