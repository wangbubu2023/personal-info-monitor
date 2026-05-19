import { describe, expect, it } from 'vitest'

import { parseKeywordBatchInput } from './keywordInputUtils'

describe('parseKeywordBatchInput', () => {
  it('supports one keyword per line', () => {
    expect(parseKeywordBatchInput('AI\nOpenAI\nAgent')).toEqual({
      keywords: ['AI', 'OpenAI', 'Agent'],
      skippedCaseDuplicates: [],
    })
  })

  it('supports comma, chinese comma, and semicolon separators', () => {
    expect(parseKeywordBatchInput('AI,OpenAI，Agent;LLM；RAG')).toEqual({
      keywords: ['AI', 'OpenAI', 'Agent', 'LLM', 'RAG'],
      skippedCaseDuplicates: [],
    })
  })

  it('trims blanks and de-duplicates case-insensitively while preserving order', () => {
    expect(parseKeywordBatchInput(' AI \n\nOpenAI,AI；ai；  Agent  ')).toEqual({
      keywords: ['AI', 'OpenAI', 'Agent'],
      skippedCaseDuplicates: ['AI', 'ai'],
    })
  })

  it('records openclaw vs Openclaw as duplicate in input', () => {
    expect(parseKeywordBatchInput('openclaw\nOpenclaw')).toEqual({
      keywords: ['openclaw'],
      skippedCaseDuplicates: ['Openclaw'],
    })
  })
})
