import type { Page, Route } from '@playwright/test'

const now = '2026-02-27T10:00:00Z'

const digestItems = [
  {
    id: 'content-1',
    source_name: 'The Wall Street Journal',
    title: 'WSJ original title',
    translated_title: 'WSJ：美股科技板块再次走强',
    summary: 'Original summary',
    translated_summary: '科技板块在财报季后继续走强，市场风险偏好回升。',
    url: 'https://www.wsj.com/articles/mock-article',
    publish_time: '2026-02-27T08:30:00Z',
    fetched_at: '2026-02-27T09:10:00Z',
    read_status: false,
    favorited: false,
    keyword_matches: [{ id: 'kw-1', keyword: '美股', color: '#6b7c3f' }],
    metadata: { reader_translation_ready: true },
  },
  {
    id: 'content-2',
    source_name: 'Economist',
    title: 'Economist original title',
    translated_title: 'Economist：欧洲能源政策再平衡',
    summary: 'Original summary 2',
    translated_summary: '政策重点从短期补贴转向长期电网和储能投资。',
    url: 'https://www.economist.com/mock-article',
    publish_time: '2026-02-27T07:20:00Z',
    fetched_at: '2026-02-27T08:00:00Z',
    read_status: true,
    favorited: false,
    keyword_matches: [],
  },
]

const sources = [
  {
    id: 'source-wsj',
    name: 'WSJ',
    type: 'website',
    url: 'https://www.wsj.com',
    extra_urls: [],
    fetch_interval: 60,
    enabled: true,
    priority: 0,
    auth_required: true,
    auth_config_id: 'auth-wsj',
    error_count: 0,
    fetch_status: 'ok',
    fetch_strategy: 'scrape',
    fetch_status_message: '可抓取',
    probe_status: 'ok',
    probe_strategy: 'scrape',
    probe_message: '探测通过',
    created_at: now,
    updated_at: now,
    last_fetched_at: now,
  },
  {
    id: 'source-economist',
    name: 'Economist',
    type: 'website',
    url: 'https://www.economist.com',
    extra_urls: [],
    fetch_interval: 60,
    enabled: true,
    priority: 0,
    auth_required: true,
    auth_config_id: 'auth-economist',
    error_count: 0,
    fetch_status: 'ok',
    fetch_strategy: 'scrape',
    fetch_status_message: '可抓取',
    probe_status: 'ok',
    probe_strategy: 'scrape',
    probe_message: '探测通过',
    created_at: now,
    updated_at: now,
    last_fetched_at: now,
  },
  {
    id: 'source-x-openai',
    name: 'OpenAI on X',
    type: 'x',
    url: 'https://x.com/OpenAI',
    extra_urls: [],
    fetch_interval: 60,
    enabled: true,
    priority: 0,
    auth_required: true,
    auth_config_id: 'auth-x',
    error_count: 0,
    fetch_status: 'ok',
    fetch_strategy: 'api',
    fetch_status_message: '可抓取',
    probe_status: 'ok',
    probe_strategy: 'api',
    probe_message: '探测通过',
    created_at: now,
    updated_at: now,
    last_fetched_at: now,
  },
]

const apiKeys = [
  {
    id: 'api-openai',
    platform: 'openai',
    name: 'OpenAI Primary',
    status: 'active',
    masked_key: 'sk-***',
    created_at: now,
    updated_at: now,
    rate_limit_info: {},
  },
  {
    id: 'api-youtube',
    platform: 'youtube',
    name: 'YT Data API',
    status: 'active',
    masked_key: 'AIza***',
    created_at: now,
    updated_at: now,
    rate_limit_info: {},
  },
]

const authConfigs = [
  {
    id: 'auth-wsj',
    site_url: 'https://www.wsj.com',
    auth_type: 'cookie',
    is_shared: false,
    status: 'active',
    login_selectors: {},
    has_credentials: true,
    bound_source_count: 0,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'auth-economist',
    site_url: 'https://www.economist.com',
    auth_type: 'cookie',
    is_shared: false,
    status: 'active',
    login_selectors: {},
    has_credentials: true,
    bound_source_count: 0,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'auth-x',
    site_url: 'https://x.com',
    auth_type: 'cookie',
    is_shared: false,
    status: 'active',
    login_selectors: {},
    has_credentials: true,
    bound_source_count: 0,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'auth-x-shared',
    name: 'E2E 共享 X',
    site_url: 'https://x.com',
    auth_type: 'cookie',
    is_shared: true,
    status: 'active',
    login_selectors: {},
    has_credentials: true,
    bound_source_count: 1,
    created_at: now,
    updated_at: now,
  },
]

const systemSettings = {
  ai_model: {
    provider: 'openai',
    model: 'gpt-4o-mini',
    temperature: 0.7,
    max_tokens: 1200,
    ollama_num_ctx: 8192,
    ollama_no_think: false,
    has_api_key: true,
  },
  translation_model: {
    provider: 'openai',
    model: 'gpt-4o-mini',
    ollama_num_ctx: 2048,
    ollama_no_think: true,
  },
  translation_enabled: true,
  title_translation_enabled: true,
  auto_translate_language: 'zh-CN',
  summarization_enabled: true,
  email_notifications_enabled: false,
  translation_fallback_enabled: false,
  translation_fallback: { provider: 'openai', model: 'gpt-4o-mini' },
  summarization_fallback_enabled: false,
  summarization_fallback: { provider: 'openai', model: 'gpt-4o-mini' },
  limits: {
    max_sources: 200,
    max_digest_candidates: 12,
    max_hourly_digest_input_items: 200,
  },
  hourly_digest: {
    prompt:
      '【选稿】从候选中挑出最值得进入本小时综述的条目。\n\n【综述】写成私人秘书式中文综述，并用 /reader/ 链接引用素材。',
    prompt_effective:
      '【选稿】从候选中挑出最值得进入本小时综述的条目。\n\n【综述】写成私人秘书式中文综述，并用 /reader/ 链接引用素材。',
    content_types: ['website', 'rss'],
  },
}

const queueStatus = {
  running_fetches: 0,
  running_processes: 0,
  fetch_concurrency: 4,
  sources_status: [
    {
      id: 'source-wsj',
      name: 'WSJ',
      type: 'website',
      url: 'https://www.wsj.com',
      enabled: true,
      fetch_interval: 60,
      last_fetched_at: now,
      next_fetch_at: null,
      error_count: 0,
      last_error: null,
      content_count: 10,
    },
  ],
}

const availableModels = {
  providers: [
    {
      id: 'openai',
      name: 'OpenAI',
      requires_api_key: true,
      default_api_base: 'https://api.openai.com/v1',
      models: [{ id: 'gpt-4o-mini', name: 'GPT-4o mini' }],
    },
    {
      id: 'qwen',
      name: 'Qwen',
      requires_api_key: true,
      models: [{ id: 'qwen-plus', name: 'Qwen Plus' }],
    },
  ],
}

const keywords = {
  items: [
    {
      id: 'kw-1',
      keyword: '美股',
      description: '市场关键词',
      match_type: 'contains',
      case_sensitive: false,
      notify: true,
      notify_email: false,
      color: '#6b7c3f',
      enabled: true,
      created_at: now,
      updated_at: now,
    },
  ],
  total: 1,
}

const hourlyDigests = [
  {
    hour: 10,
    title: '2 月 27 日 10 时简报',
    content_count: 4,
    generated_at: now,
    sources: { websites: 2, x: 1, youtube: 1, podcasts: 0 },
  },
  {
    hour: 9,
    title: '2 月 27 日 9 时简报',
    content_count: 3,
    generated_at: now,
    sources: { websites: 1, x: 1, youtube: 1, podcasts: 0 },
  },
]

const hourlyDigestDetails: Record<string, unknown> = {
  10: {
    hour: 10,
    date: '2026-02-27',
    title: '2 月 27 日 10 时简报',
    summary: [
      '## 市场动态',
      '### 美股',
      '- **科技板块**延续反弹，资金回流成长赛道。',
      '- [WSJ 原文](https://www.wsj.com/articles/mock-article) 提到盈利预期上修。',
      '',
      '### 欧洲',
      '- 能源与电网投资成为政策焦点。',
    ].join('\n'),
    content_count: 4,
    sources: ['WSJ', 'Economist', 'OpenAI on X'],
    items: digestItems,
    generated_at: now,
  },
}

const readerPayloadById: Record<string, unknown> = {
  'content-1': {
    id: 'content-1',
    source_name: 'The Wall Street Journal',
    title: 'WSJ original title',
    translated_title: 'WSJ：美股科技板块再次走强',
    original_url: 'https://www.wsj.com/articles/mock-article',
    publish_time: '2026-02-27T08:30:00Z',
    body_raw: 'raw html',
    body_zh: 'clean translated text',
    clean_html:
      '<article><h1>WSJ：美股科技板块再次走强</h1><p>这是用于 E2E 的模拟清洗译文页面。</p></article>',
  },
  'content-2': {
    id: 'content-2',
    source_name: 'Economist',
    title: 'Economist original title',
    translated_title: 'Economist：欧洲能源政策再平衡',
    original_url: 'https://www.economist.com/mock-article',
    publish_time: '2026-02-27T07:20:00Z',
    body_raw: 'raw html',
    body_zh: 'clean translated text',
    clean_html:
      '<article><h1>Economist：欧洲能源政策再平衡</h1><p>这是用于 E2E 的模拟清洗译文页面。</p></article>',
  },
}

const response = (route: Route, status: number, data: unknown) =>
  route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  })

export const mockApi = async (page: Page) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('pim_api_key', 'e2e-mock-api-key')
  })
  await page.route('**/api/**', async (route) => {
    const method = route.request().method()
    const url = new URL(route.request().url())
    const path = url.pathname

    if (method === 'GET' && path === '/api/dashboard/stats') {
      return response(route, 200, { today_total: 12, unread_count: 5, active_sources: 8, favorited_count: 1 })
    }

    if (method === 'GET' && path === '/api/digest') {
      return response(route, 200, {
        date: url.searchParams.get('date') || '2026-02-27',
        total_items: digestItems.length,
        categories: {
          websites: { count: 2, items: digestItems },
          x_accounts: { count: 0, items: [] },
          youtube: { count: 0, items: [] },
          podcasts: { count: 0, items: [] },
        },
      })
    }

    if (method === 'GET' && path === '/api/contents') {
      const q = (url.searchParams.get('search') || '').toLowerCase()
      const filtered = q
        ? digestItems.filter((item) =>
            `${item.title} ${item.translated_title} ${item.summary} ${item.translated_summary} ${item.source_name}`
              .toLowerCase()
              .includes(q)
          )
        : digestItems
      return response(route, 200, {
        items: filtered.map((item) => ({
          id: item.id,
          source_id: `source-${item.id}`,
          title: item.title,
          translated_title: item.translated_title,
          summary: item.summary,
          translated_summary: item.translated_summary,
          original_url: item.url,
          content_type: 'article',
          publish_time: item.publish_time,
          read_status: item.read_status,
          favorited: item.favorited,
          archived: false,
          keyword_matches: item.keyword_matches,
          metadata: (item as { metadata?: Record<string, unknown> }).metadata,
          fetched_at: item.fetched_at,
          created_at: now,
          updated_at: now,
          source_name: item.source_name,
        })),
        total: filtered.length,
        page: Number(url.searchParams.get('page') || 1),
        page_size: Number(url.searchParams.get('page_size') || 50),
        total_pages: 1,
      })
    }

    if (method === 'GET' && path.startsWith('/api/contents/') && path.endsWith('/reader')) {
      const id = path.split('/')[3]
      const payload = readerPayloadById[id]
      if (!payload) return response(route, 404, { detail: 'Not found' })
      return response(route, 200, payload)
    }

    if (method === 'POST' && path === '/api/sources/fetch-all') {
      return response(route, 200, { message: 'ok', task_id: 'task-1', source_count: 3 })
    }

    if (method === 'GET' && path === '/api/sources') {
      const type = url.searchParams.get('type')
      let filtered = type ? sources.filter((source) => source.type === type) : [...sources]
      const search = (url.searchParams.get('search') || '').trim().toLowerCase()
      if (search) {
        filtered = filtered.filter(
          (source) =>
            source.name.toLowerCase().includes(search) || source.url.toLowerCase().includes(search)
        )
      }
      const pageNum = Number(url.searchParams.get('page') || 1)
      const pageSize = Number(url.searchParams.get('page_size') || 20)
      const total = filtered.length
      const totalPages = Math.max(1, Math.ceil(total / pageSize))
      const start = (pageNum - 1) * pageSize
      const items = filtered.slice(start, start + pageSize)
      return response(route, 200, {
        items,
        total,
        page: pageNum,
        page_size: pageSize,
        total_pages: totalPages,
      })
    }

    if (method === 'GET' && path === '/api/configs/auth-configs') {
      return response(route, 200, authConfigs)
    }

    if (method === 'GET' && path === '/api/configs/api-keys') {
      return response(route, 200, apiKeys)
    }

    if (method === 'GET' && path === '/api/configs/browser-sessions') {
      return response(route, 200, [])
    }

    if (method === 'GET' && path === '/api/configs/settings') {
      return response(route, 200, systemSettings)
    }

    if (method === 'GET' && path === '/api/configs/ai-models/available') {
      return response(route, 200, availableModels)
    }

    if (method === 'GET' && path === '/api/keywords') {
      return response(route, 200, keywords)
    }

    if (method === 'GET' && path === '/api/digest/hourly') {
      return response(route, 200, hourlyDigests)
    }

    if (method === 'GET' && path.startsWith('/api/digest/hourly/')) {
      const hour = path.split('/').pop() || ''
      const detail = hourlyDigestDetails[hour]
      if (!detail) return response(route, 404, { detail: 'Not found' })
      return response(route, 200, detail)
    }

    if (method === 'GET' && path === '/api/system/queue') {
      return response(route, 200, queueStatus)
    }

    return response(route, 404, { detail: `Unhandled mock endpoint: ${method} ${path}` })
  })
}
