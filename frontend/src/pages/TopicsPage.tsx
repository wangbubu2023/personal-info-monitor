import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Empty, Input, Spin, message } from 'antd'
import { Archive, Plus, Tags } from 'lucide-react'
import PageHeroTitle from '../components/common/PageHeroTitle'
import { topicsApi } from '../services/topics'

const TopicsPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const { data, isLoading } = useQuery({ queryKey: ['topics'], queryFn: () => topicsApi.list() })
  const createMutation = useMutation({
    mutationFn: () => topicsApi.create({ title, creation_type: 'manual' }),
    onSuccess: async () => { setTitle(''); await queryClient.invalidateQueries({ queryKey: ['topics'] }); message.success('Topic 已创建') },
    onError: (error) => message.error(error instanceof Error ? error.message : '创建失败'),
  })
  const archiveMutation = useMutation({
    mutationFn: topicsApi.archive,
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['topics'] }); message.success('Topic 已归档') },
  })
  const items = data?.items ?? []

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-20" data-testid="topics-page">
      <div className="mx-auto max-w-page px-5 pb-5 pt-5 sm:px-8">
        <PageHeroTitle titleZh="Topic" titleEn="First-level Topic" />
        <p className="mt-2 text-sm text-[#7a8796]">Topic 是显式入口：只聚合已关联事件，不改变 Event 身份。</p>
        <div className="mt-5 flex max-w-xl gap-2">
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：AI 芯片供应链" onPressEnter={() => title.trim() && createMutation.mutate()} />
          <button type="button" disabled={!title.trim() || createMutation.isPending} onClick={() => createMutation.mutate()} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[#49A8C9] px-4 text-sm font-medium text-white disabled:opacity-50"><Plus size={15} />新建</button>
        </div>
      </div>
      <div className="mx-auto grid max-w-page gap-4 px-5 sm:grid-cols-2 sm:px-8 lg:grid-cols-3">
        {isLoading ? <div className="col-span-full flex h-48 items-center justify-center"><Spin /></div> : items.length ? items.map((topic) => (
          <article key={topic.topic_id} className="rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-3"><div className="flex items-center gap-2"><span className="rounded-xl bg-[#49A8C9]/10 p-2 text-[#3a8da9]"><Tags size={16} /></span><h2 className="font-semibold text-[#293859]">{topic.title}</h2></div><button type="button" title="归档" onClick={() => archiveMutation.mutate(topic.topic_id)} className="text-[#9aa6b4] hover:text-[#b45309]"><Archive size={16} /></button></div>
            {topic.description ? <p className="mt-3 text-sm text-[#69788a]">{topic.description}</p> : null}
            <div className="mt-5 flex flex-wrap gap-2 text-xs text-[#586476]"><span className="rounded-full bg-[#eef6fa] px-2.5 py-1">{topic.event_count} 个事件</span><span className="rounded-full bg-[#f7f4e9] px-2.5 py-1">{topic.unique_source_count} 个来源</span><span className="rounded-full bg-[#f1f3f6] px-2.5 py-1">{topic.creation_type}</span></div>
            <div className="mt-4 flex flex-wrap gap-1.5">{topic.source_coverage.slice(0, 5).map((source) => <span key={source} className="text-xs text-[#8a96a5]">{source}</span>)}</div>
          </article>
        )) : <div className="col-span-full rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white py-16"><Empty description="还没有显式 Topic" /></div>}
      </div>
    </div>
  )
}

export default TopicsPage
