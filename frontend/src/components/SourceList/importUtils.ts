import type { SourceType } from '../../types'

export interface ImportPreviewItem {
  name: string
  description: string
  url: string
  type: SourceType
}

export function detectSourceType(url: string): SourceType {
  const lowerUrl = url.toLowerCase()
  if (lowerUrl.includes('youtube.com') || lowerUrl.includes('youtu.be')) {
    return 'youtube'
  }
  if (lowerUrl.includes('x.com') || lowerUrl.includes('twitter.com')) {
    return 'x'
  }
  if (lowerUrl.includes('feed') || lowerUrl.includes('/rss') || lowerUrl.endsWith('.xml')) {
    return 'rss'
  }
  return 'website'
}

export function parseUrlLines(value?: string): string[] {
  if (!value) return []
  const seen = new Set<string>()
  const urls: string[] = []
  for (const line of value.split('\n')) {
    const item = line.trim()
    if (!item || seen.has(item)) continue
    seen.add(item)
    urls.push(item)
  }
  return urls
}

export function parseCSV(content: string): Array<{ name: string; description: string; url: string }> {
  const lines = content.split('\n').filter(line => line.trim())
  const result: Array<{ name: string; description: string; url: string }> = []

  // Skip header row
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i]
    // Handle CSV with commas in quoted fields
    const matches = line.match(/("([^"]|"")*"|[^,]*)(,("([^"]|"")*"|[^,]*))*/g)
    if (matches) {
      const parts: string[] = []
      let currentField = ''
      let inQuotes = false

      for (let j = 0; j < line.length; j++) {
        const char = line[j]
        if (char === '"') {
          inQuotes = !inQuotes
        } else if (char === ',' && !inQuotes) {
          parts.push(currentField.trim().replace(/^"|"$/g, '').replace(/""/g, '"'))
          currentField = ''
        } else {
          currentField += char
        }
      }
      parts.push(currentField.trim().replace(/^"|"$/g, '').replace(/""/g, '"'))

      if (parts.length >= 3 && parts[0] && parts[2]) {
        result.push({
          name: parts[0],
          description: parts[1] || '',
          url: parts[2],
        })
      }
    }
  }

  return result
}
