export type AtomType = '信息' | '观点' | '数据'

export interface AtomRecord {
  atom_id: string
  content_id: string
  atom_type: AtomType
  domain: string
  source_sentence: string
  source_url: string
  atom_source: string
  payload: Record<string, unknown>
  verified: boolean
  source_credibility: number
  fact_confidence: number
  schema_version: number
  created_at: string
  updated_at: string
}

export interface AtomListResponse {
  items: AtomRecord[]
  total: number
  page: number
  page_size: number
}

export interface AtomStatsResponse {
  total: number
  by_type: Record<string, number>
  by_domain: Record<string, number>
  verified_count: number
  unverified_count: number
}

export interface AtomListParams {
  type?: string
  domain?: string
  verified?: boolean
  atom_source?: string
  content_id?: string
  search?: string
  page?: number
  page_size?: number
}

export interface AtomUpdatePayload {
  domain?: string
  atom_source?: string
  source_credibility?: number
  fact_confidence?: number
  verified?: boolean
  payload?: Record<string, unknown>
}

export type RelationType =
  | '因果'
  | '递进'
  | '转折'
  | '矛盾'
  | '印证'
  | '背景'
  | '并列'

export type RelationDirection = 'A→B' | 'B→A' | '双向'

export interface RelationRecord {
  rel_id: string
  atom_a: string
  atom_b: string
  relation_type: RelationType
  direction: RelationDirection
  verified: boolean
  fact_confidence: number
  created_at: string
  updated_at: string
}

export interface RelationListResponse {
  items: RelationRecord[]
}

export interface RelationCreatePayload {
  atom_a: string
  atom_b: string
  relation_type: RelationType
  direction: RelationDirection
  fact_confidence: number
  verified?: boolean
}
