export interface ReaderLayoutProfile {
  key: 'default' | 'nyt-cn' | 'economist' | 'wsj'
  articleClassName: string
  bodyClassName: string
  figureClassName: string
  codeClassName: string
  footnoteClassName: string
}

const DEFAULT_PROFILE: ReaderLayoutProfile = {
  key: 'default',
  articleClassName: 'space-y-14',
  bodyClassName: 'max-w-none text-[18px] leading-[1.85] text-[#293859]',
  figureClassName: 'my-10 overflow-hidden rounded-lg border border-[rgba(88,100,118,0.14)] bg-white',
  codeClassName: 'my-9 max-w-full overflow-x-auto rounded-lg bg-[#1f2937] p-5 text-[14px] leading-[1.7] text-[#f8fafc]',
  footnoteClassName: 'my-7 border-t border-[rgba(88,100,118,0.12)] pt-4 text-[14px] leading-[1.75] text-[#586476]',
}

const PAID_SOURCE_PROFILES: ReaderLayoutProfile[] = [
  {
    key: 'nyt-cn',
    articleClassName: 'space-y-12',
    bodyClassName: 'max-w-none text-[18px] leading-[1.95] text-[#26344f]',
    figureClassName: 'my-11 overflow-hidden border-y border-[rgba(88,100,118,0.16)] bg-white py-4',
    codeClassName: DEFAULT_PROFILE.codeClassName,
    footnoteClassName: 'my-7 border-t border-[#8C866A]/22 pt-4 text-[14px] leading-[1.85] text-[#5f6f82]',
  },
  {
    key: 'economist',
    articleClassName: 'space-y-12',
    bodyClassName: 'max-w-none text-[18px] leading-[1.9] text-[#293859]',
    figureClassName: 'my-10 overflow-hidden rounded border border-[#8C866A]/22 bg-[#fffdf8]',
    codeClassName: 'my-9 max-w-full overflow-x-auto rounded bg-[#27313f] p-5 text-[14px] leading-[1.75] text-[#f8fafc]',
    footnoteClassName: 'my-7 border-l-2 border-[#8C866A]/45 bg-[#fffdf8] px-4 py-3 text-[14px] leading-[1.8] text-[#586476]',
  },
  {
    key: 'wsj',
    articleClassName: 'space-y-12',
    bodyClassName: 'max-w-none text-[17px] leading-[1.9] text-[#26344f]',
    figureClassName: 'my-9 overflow-hidden rounded-sm border border-[rgba(88,100,118,0.18)] bg-white',
    codeClassName: 'my-9 max-w-full overflow-x-auto rounded-sm bg-[#172033] p-5 text-[13px] leading-[1.75] text-[#f8fafc]',
    footnoteClassName: 'my-7 border-t border-[rgba(88,100,118,0.16)] pt-4 text-[13px] leading-[1.75] text-[#5f6f82]',
  },
]

export function getReaderLayoutProfile(originalUrl?: string, sourceName?: string): ReaderLayoutProfile {
  const value = `${originalUrl || ''} ${sourceName || ''}`.toLowerCase()
  if (value.includes('cn.nytimes.com') || value.includes('纽约时报')) return PAID_SOURCE_PROFILES[0]
  if (value.includes('economist.com') || value.includes('economist')) return PAID_SOURCE_PROFILES[1]
  if (value.includes('wsj.com') || value.includes('wall street journal') || value.includes('wsj')) {
    return PAID_SOURCE_PROFILES[2]
  }
  return DEFAULT_PROFILE
}
