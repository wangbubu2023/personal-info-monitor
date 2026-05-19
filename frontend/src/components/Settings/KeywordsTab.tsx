import React, { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Form, Input, Popconfirm, Space, Table, Tag, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { keywordsApi } from '../../services/keywords'
import type {
  Keyword,
  KeywordBatchCreate,
  KeywordBatchUpdate,
  KeywordCreate,
  KeywordMatchScope,
  MatchType,
} from '../../types'
import SectionNote from '../ui/SectionNote'
import { parseKeywordBatchInput } from './keywordInputUtils'
import {
  KEYWORD_LABEL_COLORS,
  matchScopeLabels,
  matchTypeLabels,
} from './keywords/keywordConstants'
import {
  getMutationErrorMessage,
  keywordRowMatchesSearch,
  mergeFinishWithFormStore,
  normalizeIncludeAutoEquivalent,
  normalizePaletteColor,
  pickFormBoolean,
  warnSkippedCaseDuplicates,
} from './keywords/keywordHelpers'
import KeywordBulkBar from './keywords/KeywordBulkBar'
import KeywordFormModal from './keywords/KeywordFormModal'

const KeywordsTab: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null)
  const [listSearchText, setListSearchText] = useState('')
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<string[]>([])
  const [bulkColor, setBulkColor] = useState<string>()
  const [bulkMatchScope, setBulkMatchScope] = useState<KeywordMatchScope>()
  const [bulkMatchType, setBulkMatchType] = useState<MatchType>()
  const [bulkEnabled, setBulkEnabled] = useState<boolean>()
  const [form] = Form.useForm()
  /** 与 Switch 实时同步，避免 onFinish / getFieldsValue 在部分环境下丢失 false */
  const watchedIncludeAuto = Form.useWatch('include_auto_equivalent_terms', form)
  const queryClient = useQueryClient()

  /** 弹窗打开后再 setFieldsValue，避免 Switch 的 Form.Item initialValue 与「编辑/添加」分支切换时覆盖为「开」 */
  useEffect(() => {
    if (!isModalOpen || !editingKeyword) return
    const record = editingKeyword
    const {
      equivalent_terms: _eq,
      manual_equivalent_terms: _man,
      created_at: _c,
      updated_at: _u,
      id: _id,
      ...editable
    } = record
    form.setFieldsValue({
      ...editable,
      color: normalizePaletteColor(record.color),
      manualEquivalentsText: (record.manual_equivalent_terms ?? []).join('\n'),
      include_auto_equivalent_terms: normalizeIncludeAutoEquivalent(record.include_auto_equivalent_terms),
    })
  }, [isModalOpen, editingKeyword, form])

  const { data: keywordsData, isLoading } = useQuery({
    queryKey: ['keywords'],
    queryFn: () => keywordsApi.list(),
  })

  const filteredKeywordItems = useMemo(() => {
    const items = keywordsData?.items ?? []
    if (!listSearchText.trim()) return items
    return items.filter((row) => keywordRowMatchesSearch(row, listSearchText))
  }, [keywordsData?.items, listSearchText])

  const createBatchMutation = useMutation({
    mutationFn: keywordsApi.createBatch,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['keywords'] })
      const sk = result.skipped_keywords
      if (result.total === 0 && sk.length > 0) {
        const preview = sk.slice(0, 12).join('、')
        const more = sk.length > 12 ? ` 等共 ${sk.length} 项` : ''
        message.warning(`未新增搜索词。以下与已有词重复（忽略大小写）已跳过：${preview}${more}`)
      } else if (result.total > 0 && sk.length > 0) {
        message.success(`已创建 ${result.total} 个搜索词`)
        const preview = sk.slice(0, 12).join('、')
        const more = sk.length > 12 ? ` 等共 ${sk.length} 项` : ''
        message.warning(`以下未创建（与已有搜索词重复，忽略大小写）：${preview}${more}`)
      } else {
        message.success(`已创建 ${result.total} 个搜索词`)
      }
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: (error) => {
      message.error(getMutationErrorMessage(error, '创建搜索词失败'))
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<KeywordCreate> }) => keywordsApi.update(id, data),
    onSuccess: async (updated: Keyword) => {
      queryClient.setQueryData<{ items: Keyword[]; total: number } | undefined>(['keywords'], (old) => {
        if (!old) return old
        return {
          ...old,
          items: old.items.map((k) => (k.id === updated.id ? { ...k, ...updated } : k)),
        }
      })
      // 等待列表与 PATCH 结果对齐，避免 invalidate 异步竞态导致仍显示旧等价词
      await queryClient.refetchQueries({ queryKey: ['keywords'] })
      message.success('更新成功。历史内容的关键词匹配会在后台刷新，资讯里可能要过几秒才一致。')
      setIsModalOpen(false)
      setEditingKeyword(null)
      form.resetFields()
    },
    onError: (error) => {
      message.error(getMutationErrorMessage(error, '更新搜索词失败'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: keywordsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['keywords'] })
      message.success('删除成功')
    },
    onError: (error) => {
      message.error(getMutationErrorMessage(error, '删除搜索词失败'))
    },
  })

  const batchUpdateMutation = useMutation({
    mutationFn: keywordsApi.updateBatch,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['keywords'] })
      message.success(`已批量更新 ${result.total} 个关键词`)
      setSelectedKeywordIds([])
      setBulkColor(undefined)
      setBulkMatchScope(undefined)
      setBulkMatchType(undefined)
      setBulkEnabled(undefined)
    },
    onError: (error) => {
      message.error(getMutationErrorMessage(error, '批量更新关键词失败'))
    },
  })

  const columns = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      key: 'keyword',
      width: 140,
      render: (keyword: string, record: Keyword) => <Tag color={record.color}>{keyword}</Tag>,
    },
    {
      title: '等价词',
      key: 'equivalent_terms',
      ellipsis: true,
      render: (_: unknown, record: Keyword) => {
        if (!record.equivalent_terms?.length) return null
        return record.equivalent_terms.join(' / ')
      },
    },
    {
      title: '匹配类型',
      dataIndex: 'match_type',
      key: 'match_type',
      render: (type: MatchType) => matchTypeLabels[type] || type,
    },
    {
      title: '生效范围',
      dataIndex: 'match_scope',
      key: 'match_scope',
      render: (scope: KeywordMatchScope) => matchScopeLabels[scope] || scope,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (enabled: boolean) => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '禁用'}</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: Keyword) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setEditingKeyword(record)
              setIsModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定要删除这个关键词吗？" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys: selectedKeywordIds,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedKeywordIds(newSelectedRowKeys.map(String))
    },
  }

  const handleSubmit = (finishValues: Record<string, unknown>) => {
    const values = mergeFinishWithFormStore(form, finishValues)
    const manualText = String(form.getFieldValue('manualEquivalentsText') ?? values.manualEquivalentsText ?? '')
    const manualParsed = parseKeywordBatchInput(manualText)
    warnSkippedCaseDuplicates('手动等价词', manualParsed.skippedCaseDuplicates)
    const includeAuto =
      watchedIncludeAuto === true || watchedIncludeAuto === false
        ? watchedIncludeAuto
        : pickFormBoolean(
            'include_auto_equivalent_terms',
            finishValues,
            values,
            form,
            editingKeyword ? normalizeIncludeAutoEquivalent(editingKeyword.include_auto_equivalent_terms) : true,
          )

    if (editingKeyword) {
      updateMutation.mutate({
        id: editingKeyword.id,
        data: {
          keyword: String(values.keyword ?? '').trim(),
          description: (values.description as string | undefined) || undefined,
          match_type: values.match_type as KeywordCreate['match_type'],
          match_scope: values.match_scope as KeywordCreate['match_scope'],
          case_sensitive: pickFormBoolean('case_sensitive', finishValues, values, form, editingKeyword.case_sensitive ?? false),
          manual_equivalent_terms: manualParsed.keywords,
          include_auto_equivalent_terms: includeAuto,
          notify: false,
          notify_email: false,
          color: normalizePaletteColor(values.color),
          enabled: pickFormBoolean('enabled', finishValues, values, form, editingKeyword.enabled ?? true),
        },
      })
      return
    }

    const keywordsParsed = parseKeywordBatchInput(String(values.keywordsText || ''))
    warnSkippedCaseDuplicates('搜索词', keywordsParsed.skippedCaseDuplicates)
    if (keywordsParsed.keywords.length === 0) {
      message.error('请至少输入一个搜索词')
      return
    }

    const payload: KeywordBatchCreate = {
      keywords: keywordsParsed.keywords,
      description: values.description as string | undefined,
      match_type: values.match_type as KeywordBatchCreate['match_type'],
      match_scope: values.match_scope as KeywordBatchCreate['match_scope'],
      case_sensitive: pickFormBoolean('case_sensitive', finishValues, values, form, false),
      manual_equivalent_terms: manualParsed.keywords,
      include_auto_equivalent_terms: includeAuto,
      notify: false,
      notify_email: false,
      color: normalizePaletteColor(values.color),
      enabled: pickFormBoolean('enabled', finishValues, values, form, true),
    }
    createBatchMutation.mutate(payload)
  }

  const applyBatchUpdates = () => {
    if (selectedKeywordIds.length === 0) {
      message.error('请先选择要批量修改的关键词')
      return
    }

    const payload: KeywordBatchUpdate = { keyword_ids: selectedKeywordIds }
    if (bulkColor) payload.color = bulkColor
    if (bulkMatchScope) payload.match_scope = bulkMatchScope
    if (bulkMatchType) payload.match_type = bulkMatchType
    if (bulkEnabled !== undefined) payload.enabled = bulkEnabled

    if (
      payload.color === undefined
      && payload.match_scope === undefined
      && payload.match_type === undefined
      && payload.enabled === undefined
    ) {
      message.error('请至少选择一项：颜色、生效范围、匹配类型或启用状态')
      return
    }

    batchUpdateMutation.mutate(payload)
  }

  const clearBulkSelection = () => {
    setSelectedKeywordIds([])
    setBulkColor(undefined)
    setBulkMatchScope(undefined)
    setBulkMatchType(undefined)
    setBulkEnabled(undefined)
  }

  return (
    <div className="p-4 sm:p-5">
      <SectionNote
        className="mb-4"
        title="关键词如何生效"
        collapsible
        defaultOpen={false}
        storageKey="pim.settings.keywordsHelpOpen"
      >
        <ul className="space-y-1.5">
          <li className="flex gap-2">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#49A8C9]/70" aria-hidden />
            <span>
              在「<strong className="font-semibold text-[#2c3a50]">监测源</strong>」中为信源开启「启用关键词过滤」后，仅当<strong className="font-semibold text-[#2c3a50]">标题或正文</strong>匹配本列表中至少一个词时，内容才会入库。
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#8C866A]/55" aria-hidden />
            <span>
              未开启过滤的信源仍按原逻辑<strong className="font-semibold text-[#2c3a50]">全量入库</strong>，不受此列表影响。
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#49A8C9]/70" aria-hidden />
            <span>
              添加搜索词时支持<strong className="font-semibold text-[#2c3a50]">批量输入</strong>：可以<strong className="font-semibold text-[#2c3a50]">一行一个</strong>，也可以使用<strong className="font-semibold text-[#2c3a50]">逗号、中文逗号、分号</strong>分隔。
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#49A8C9]/70" aria-hidden />
            <span>
              默认会<strong className="font-semibold text-[#2c3a50]">合并自动翻译等价词</strong>；可在编辑中<strong className="font-semibold text-[#2c3a50]">手动补充或关闭自动</strong>，避免「苹果」「元」等错误机翻影响匹配。
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#8C866A]/55" aria-hidden />
            <span>
              每个关键词都可以单独指定生效范围为<strong className="font-semibold text-[#2c3a50]">标题、正文、标题 + 正文</strong>；表格多选后可批量修改颜色、生效范围、匹配类型以及启用状态。
            </span>
          </li>
        </ul>
      </SectionNote>

      <div className="mb-4 flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1 sm:max-w-md">
          <Input.Search
            allowClear
            placeholder="搜索关键词、描述或等价词…"
            value={listSearchText}
            onChange={(e) => setListSearchText(e.target.value)}
            className="!w-full"
            aria-label="筛选关键词列表"
          />
          {keywordsData?.items?.length ? (
            <div className="text-[12px] text-[#6d7c8d]">
              {listSearchText.trim()
                ? `共 ${keywordsData.items.length} 条，匹配 ${filteredKeywordItems.length} 条`
                : `共 ${keywordsData.items.length} 条`}
            </div>
          ) : null}
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingKeyword(null)
            form.resetFields()
            setIsModalOpen(true)
            queueMicrotask(() => {
              form.setFieldsValue({
                match_type: 'contains',
                match_scope: 'title_content',
                include_auto_equivalent_terms: true,
                color: KEYWORD_LABEL_COLORS[0],
                enabled: true,
              })
            })
          }}
          className="shrink-0 !h-8 !rounded-lg !px-3.5 !text-[13px] !font-medium shadow-sm"
        >
          添加搜索词
        </Button>
      </div>

      <KeywordBulkBar
        selectedCount={selectedKeywordIds.length}
        color={bulkColor}
        matchScope={bulkMatchScope}
        matchType={bulkMatchType}
        enabled={bulkEnabled}
        isApplying={batchUpdateMutation.isPending}
        onColorChange={setBulkColor}
        onMatchScopeChange={setBulkMatchScope}
        onMatchTypeChange={setBulkMatchType}
        onEnabledChange={setBulkEnabled}
        onClear={clearBulkSelection}
        onApply={applyBatchUpdates}
      />

      <Table
        columns={columns}
        dataSource={filteredKeywordItems}
        loading={isLoading}
        rowKey="id"
        rowSelection={rowSelection}
      />

      <KeywordFormModal
        open={isModalOpen}
        editing={editingKeyword}
        form={form}
        onCancel={() => setIsModalOpen(false)}
        onFinish={handleSubmit}
        submitLoading={createBatchMutation.isPending || updateMutation.isPending}
      />
    </div>
  )
}

export default KeywordsTab
