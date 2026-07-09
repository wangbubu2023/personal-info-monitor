import { invoke } from '@tauri-apps/api/core'
import JSZip from 'jszip'
import type { SavedBundle } from './storage'

export interface DesktopCaptureResult {
  bundle: unknown
  site_host: string
  name: string
}

export interface DesktopExportResult {
  path: string
  profile_count: number
}

export async function isDesktopRuntime(): Promise<boolean> {
  if (!('__TAURI_INTERNALS__' in window)) return false
  try {
    return await invoke<boolean>('is_desktop_runtime')
  } catch {
    return false
  }
}

export async function captureAuthBundle(siteUrl: string, dwellSeconds: number): Promise<DesktopCaptureResult> {
  return invoke<DesktopCaptureResult>('capture_auth_bundle', {
    siteUrl,
    dwellSeconds,
  })
}

export async function exportAuthZipDesktop(bundles: SavedBundle[]): Promise<DesktopExportResult> {
  return invoke<DesktopExportResult>('export_auth_zip', {
    bundles: bundles.map((item) => ({
      name: item.name,
      site_host: item.siteHost,
      bundle: item.bundle,
    })),
  })
}

export async function exportAuthZipBrowser(bundles: SavedBundle[]): Promise<DesktopExportResult> {
  if (bundles.length === 0) {
    throw new Error('请选择至少一个登录态')
  }
  const zip = new JSZip()
  const profiles = bundles.map((item, index) => {
    const file = `profiles/${index + 1}-${safeFileStem(item.siteHost)}.auth.json`
    zip.file(file, JSON.stringify(item.bundle, null, 2))
    return {
      site_host: item.siteHost,
      name: item.name,
      file,
    }
  })
  zip.file(
    'manifest.json',
    JSON.stringify(
      {
        kind: 'pim.auth_export',
        version: 1,
        created_at: new Date().toISOString(),
        profiles,
      },
      null,
      2,
    ),
  )
  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE' })
  const filename = `pim-auth-export-${Date.now()}.zip`
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
  return { path: filename, profile_count: bundles.length }
}

function safeFileStem(value: string): string {
  const stem = value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '')
  return stem || 'profile'
}
