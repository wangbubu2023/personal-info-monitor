import { useState, useRef } from 'react'
import { message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { sourceKeys } from '../../../services/queryKeys'
import type { SourceCreate } from '../../../types'
import { detectSourceType, parseCSV, type ImportPreviewItem } from '../importUtils'

export type { ImportPreviewItem }

interface UseSourceImportOptions {
  remainingSources: number
}

export function useSourceImport({ remainingSources }: UseSourceImportOptions) {
  const [isImportModalOpen, setIsImportModalOpen] = useState(false)
  const [importPreview, setImportPreview] = useState<ImportPreviewItem[]>([])
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const bulkImportMutation = useMutation({
    mutationFn: sourcesApi.bulkImport,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功导入 ${data.length} 个监控源`)
      setIsImportModalOpen(false)
      setImportPreview([])
    },
    onError: () => {
      message.error('导入失败')
    },
  })

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result as string
      const parsed = parseCSV(content)
      const preview: ImportPreviewItem[] = parsed.map((item) => ({
        ...item,
        type: detectSourceType(item.url),
      }))
      setImportPreview(preview)
      setIsImportModalOpen(true)
    }
    reader.readAsText(file, 'UTF-8')

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleBulkImport = async () => {
    if (importPreview.length === 0) return
    if (importPreview.length > remainingSources) {
      message.error(
        `导入失败：还可新增 ${remainingSources} 个信源，本次准备导入 ${importPreview.length} 个。`
      )
      return
    }

    setIsImporting(true)

    const sourcesToImport: SourceCreate[] = importPreview.map((item) => ({
      name: item.name,
      type: item.type,
      url: item.url,
      metadata: item.description ? { description: item.description } : undefined,
      fetch_interval: 60,
      enabled: true,
      priority: 0,
    }))

    try {
      await bulkImportMutation.mutateAsync(sourcesToImport)
    } finally {
      setIsImporting(false)
    }
  }

  return {
    isImportModalOpen,
    setIsImportModalOpen,
    importPreview,
    setImportPreview,
    isImporting,
    fileInputRef,
    bulkImportMutation,
    handleFileSelect,
    handleBulkImport,
  }
}
