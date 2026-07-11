import React, { Suspense, lazy, useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import MainLayout from './components/layout/MainLayout'
import Spotlight from './components/common/Spotlight'
import { SCORE_LAB_BUILD_ENABLED } from './config/features'

const HomePage = lazy(() => import('./pages/HomePage'))
const DigestPage = lazy(() => import('./pages/DigestPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const ReaderPage = lazy(() => import('./pages/ReaderPage'))
const EventDetailPage = lazy(() => import('./pages/EventDetailPage'))
const AtomsPage = lazy(() => import('./pages/AtomsPage'))
const ScoreLabPage = lazy(() => import('./pages/ScoreLabPage'))

const App: React.FC = () => {
  const [isSpotlightOpen, setIsSpotlightOpen] = useState<boolean>(false)

  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setIsSpotlightOpen(prev => !prev)
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [])

  return (
    <MainLayout>
      <Spotlight isOpen={isSpotlightOpen} onClose={() => setIsSpotlightOpen(false)} />
      <AnimatePresence mode="wait">
        <Suspense fallback={
          <div className="flex h-[50vh] items-center justify-center">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-[#586476] font-medium tracking-[0.14em] text-xs uppercase"
            >
              正在加载…
            </motion.div>
          </div>
        }>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route path="/reader/:id" element={<ReaderPage />} />
            <Route path="/events/:eventId" element={<EventDetailPage />} />
            <Route path="/atoms" element={<AtomsPage />} />
            {SCORE_LAB_BUILD_ENABLED ? <Route path="/score-lab" element={<ScoreLabPage />} /> : null}
            <Route path="/sources" element={<Navigate to="/settings" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AnimatePresence>
    </MainLayout>
  )
}

export default App
