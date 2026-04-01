import React, { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Header } from './components/layout'

const HomePage = lazy(() => import('./pages/HomePage'))
const DigestPage = lazy(() => import('./pages/DigestPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const ReaderPage = lazy(() => import('./pages/ReaderPage'))

const App: React.FC = () => {
  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <Header />
      <main>
        <Suspense fallback={<div style={{ padding: 24, color: '#666' }}>页面加载中...</div>}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route path="/reader/:id" element={<ReaderPage />} />
            <Route path="/sources" element={<Navigate to="/settings" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}

export default App
