/** 与后端 keyword_identity_key 一致：用于输入去重（ASCII/常用脚本下与 casefold 行为接近） */
function inputIdentityKey(value: string): string {
  return value.trim().toLocaleLowerCase()
}

export type ParsedKeywordBatchInput = {
  keywords: string[]
  /** 与前面已保留的词仅大小写不同（或重复出现）而被舍弃的片段，保留用户原始写法便于提示 */
  skippedCaseDuplicates: string[]
}

/**
 * 解析多行/逗号分隔的搜索词或手动等价词。
 * 同一输入内仅大小写不同的词只保留首次出现，其余记入 skippedCaseDuplicates。
 */
export function parseKeywordBatchInput(raw: string): ParsedKeywordBatchInput {
  const seen = new Set<string>()
  const keywords: string[] = []
  const skippedCaseDuplicates: string[] = []
  const values = (raw || '')
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  for (const value of values) {
    const dedupeKey = inputIdentityKey(value)
    if (seen.has(dedupeKey)) {
      skippedCaseDuplicates.push(value)
      continue
    }
    seen.add(dedupeKey)
    keywords.push(value)
  }
  return { keywords, skippedCaseDuplicates }
}
