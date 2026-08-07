import React, { Suspense, lazy, useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import MainLayout from './components/layout/MainLayout'
import Spotlight from './components/common/Spotlight'
import { SCORE_LAB_BUILD_ENABLED } from './config/features'

const TodayHighlightsPage = lazy(() => import('./pages/TodayHighlightsPage'))
const HomePage = lazy(() => import('./pages/HomePage'))
const DigestPage = lazy(() => import('./pages/DigestPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const ReaderPage = lazy(() => import('./pages/ReaderPage'))
const EventDetailPage = lazy(() => import('./pages/EventDetailPage'))
const ScoreLabPage = lazy(() => import('./pages/ScoreLabPage'))
const AtomsPage = lazy(() => import('./pages/AtomsPage'))
const AnnotationReviewPage = lazy(() => import('./pages/AnnotationReviewPage'))
const TopicsPage = lazy(() => import('./pages/TopicsPage'))
const BriefsPage = lazy(() => import('./pages/BriefsPage'))

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
            <Route path="/" element={<TodayHighlightsPage />} />
            <Route path="/timeline" element={<HomePage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route path="/topics" element={<TopicsPage />} />
            <Route path="/briefs" element={<BriefsPage />} />
            <Route path="/reader/:id" element={<ReaderPage />} />
            <Route path="/events" element={<Navigate to="/" replace />} />
            <Route path="/events/:eventId" element={<EventDetailPage />} />
            <Route path="/atoms" element={<AtomsPage />} />
            <Route path="/review" element={<AnnotationReviewPage />} />
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
