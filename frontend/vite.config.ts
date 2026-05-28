import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'node:fs'

const tauriHost = process.env.TAURI_DEV_HOST
const devHost = process.env.PIM_DEV_HOST || tauriHost || '127.0.0.1'
const packageJson = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')) as { version?: string }
const appVersion = packageJson.version || '0.0.0'

// https://v2.tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  clearScreen: false,
  envPrefix: ['VITE_', 'TAURI_ENV_*'],
  server: {
    port: 3000,
    strictPort: true,
    host: devHost,
    hmr: tauriHost
      ? {
          protocol: 'ws',
          host: tauriHost,
          port: 1421,
        }
      : undefined,
    watch: {
      ignored: ['**/src-tauri/**'],
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13',
    minify: !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules/')) {
            return
          }
          const modulePath = id.split('node_modules/')[1]
          const parts = modulePath.split('/')
          const pkg = parts[0].startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0]

          if (pkg === 'react' || pkg === 'react-dom' || pkg === 'react-router' || pkg === 'react-router-dom') {
            return 'react-vendor'
          }
          if (pkg === '@tanstack/react-query') {
            return 'query-vendor'
          }
          if (pkg === 'antd') {
            return
          }
          if (pkg === '@ant-design/icons' || pkg === '@ant-design/icons-svg' || pkg.startsWith('rc-')) {
            return `antd-${pkg.replace('@', '').replace('/', '-')}`
          }
          return `vendor-${pkg.replace('@', '').replace('/', '-')}`
        },
      },
    },
  },
})
