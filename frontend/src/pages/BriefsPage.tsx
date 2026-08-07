import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Empty, Input, Select, Spin, message } from 'antd'
import { FileText, RefreshCw } from 'lucide-react'
import PageHeroTitle from '../components/common/PageHeroTitle'
import { briefsApi } from '../services/briefs'

const BriefsPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState('')
  const [type, setType] = useState<'weekly' | 'monthly'>('weekly')
  const { data, isLoading } = useQuery({ queryKey: ['briefs'], queryFn: () => briefsApi.list() })
  const generateMutation = useMutation({
    mutationFn: (payload: { periodKey: string; briefType: 'weekly' | 'monthly'; regenerate: boolean }) => briefsApi.generate({ period_key: payload.periodKey, brief_type: payload.briefType, regenerate: payload.regenerate }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['briefs'] }); message.success('Brief 已生成') },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成失败'),
  })
  const items = data?.items ?? []
  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-20" data-testid="briefs-page">
      <div className="mx-auto max-w-page px-5 pb-5 pt-5 sm:px-8">
        <PageHeroTitle titleZh="Brief" titleEn="Immutable Weekly / Monthly Brief" />
        <p className="mt-2 text-sm text-[#7a8796]">Brief 只从不可变 EventSnapshot 生成；再生成会产生新版本并保留 lineage。</p>
        <div className="mt-5 flex max-w-2xl flex-wrap gap-2">
          <Input className="!w-40" value={period} onChange={(event) => setPeriod(event.target.value)} placeholder={type === 'weekly' ? '2026-W32' : '2026-08'} />
          <Select value={type} onChange={setType} options={[{ value: 'weekly', label: '周报' }, { value: 'monthly', label: '月报' }]} />
          <button type="button" disabled={!period.trim() || generateMutation.isPending} onClick={() => generateMutation.mutate({ periodKey: period, briefType: type, regenerate: false })} className="inline-flex items-center gap-1.5 rounded-lg bg-[#49A8C9] px-4 text-sm font-medium text-white disabled:opacity-50"><FileText size={15} />生成</button>
        </div>
      </div>
      <div className="mx-auto max-w-page space-y-4 px-5 sm:px-8">
        {isLoading ? <div className="flex h-48 items-center justify-center"><Spin /></div> : items.length ? items.map((brief) => (
          <article key={brief.brief_id} className="rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="rounded-xl bg-[#8C866A]/10 p-2 text-[#8C866A]"><FileText size={16} /></span><h2 className="font-semibold text-[#293859]">{brief.title}</h2><span className="rounded-full bg-[#eef2f8] px-2 py-0.5 text-xs text-[#586476]">v{brief.version}</span></div><p className="mt-2 text-xs text-[#8a96a5]">{brief.period_key} · {brief.publication_status} · modality {brief.modality_status}</p></div><button type="button" disabled={generateMutation.isPending} onClick={() => { setPeriod(brief.period_key); setType(brief.brief_type as 'weekly' | 'monthly'); generateMutation.mutate({ periodKey: brief.period_key, briefType: brief.brief_type as 'weekly' | 'monthly', regenerate: true }) }} className="inline-flex items-center gap-1.5 rounded-lg border border-[#49A8C9]/20 px-3 py-1.5 text-xs text-[#3a8da9] disabled:opacity-40"><RefreshCw size={13} />再生成</button></div>
            <p className="mt-4 whitespace-pre-line text-sm leading-relaxed text-[#586476]">{brief.summary_content}</p>
            <p className="mt-4 text-xs text-[#9aa6b4]">输入快照：{Array.isArray(brief.lineage_snapshot?.source_event_snapshot_ids) ? brief.lineage_snapshot.source_event_snapshot_ids.length : 0} 条</p>
          </article>
        )) : <div className="rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white py-16"><Empty description="还没有 Brief" /></div>}
      </div>
    </div>
  )
}

export default BriefsPage
