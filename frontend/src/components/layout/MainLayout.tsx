import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  BookOpen,
  Newspaper,
  Clock,
  SlidersHorizontal,
  Search,
  Command,
  Menu,
  X,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface SidebarItemProps {
  to: string;
  label: string;
  icon: React.ElementType;
  isActive: boolean;
  onClick?: () => void;
}

const iconStroke = 1.5

/** 侧栏分组标题：不透明深色胶囊（与侧栏底色差），区别于下方半透明可点击项；不用竖线以免与选中条重复 */
const NavSectionLabel: React.FC = () => (
  <span className="inline-flex w-fit items-center rounded-full bg-[#1e2c3f] px-3 py-1.5 text-[11px] font-semibold tracking-[0.2em] text-[#9eb0c4] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
    导航
  </span>
);

const SidebarItem: React.FC<SidebarItemProps> = ({ to, label, icon: Icon, isActive, onClick }) => (
  <Link
    to={to}
    onClick={onClick}
    className={`group relative flex items-center gap-3 rounded-[1.3rem] border px-3.5 py-[0.82rem] transition-all duration-200 ${
      isActive
        ? 'border-white/[0.11] bg-[linear-gradient(135deg,rgba(83,141,188,0.34),rgba(63,84,128,0.44))] text-[#e7f1f7] shadow-[0_16px_30px_-24px_rgba(73,168,201,0.72)]'
        : 'border-transparent text-[#a8bfcf] hover:border-white/[0.08] hover:bg-white/[0.045] hover:text-[#D1E0E9]'
    }`}
  >
    {isActive && (
      <motion.div
        layoutId="sidebar-active"
        className="absolute left-1.5 h-8.5 w-[3px] rounded-full bg-gradient-to-b from-[#8de2f4] to-[#49A8C9]"
        transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
      />
    )}
    <span
      className={`flex h-10.5 w-10.5 shrink-0 items-center justify-center rounded-[1rem] border transition-colors ${
        isActive
          ? 'border-[#89dcef]/16 bg-[linear-gradient(135deg,rgba(73,168,201,0.2),rgba(137,220,239,0.08))] text-[#b9f0fb]'
          : 'border-white/[0.07] bg-white/[0.035] text-[#8ea3b8] group-hover:border-white/10 group-hover:bg-white/[0.06] group-hover:text-[#c5d6e3]'
      }`}
    >
      <Icon className="h-[18px] w-[18px]" strokeWidth={iconStroke} />
    </span>
    <span className="flex-1 text-[15px] font-medium tracking-[-0.01em]">{label}</span>
  </Link>
);

const MainLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const navItems = [
    { to: '/', label: '资讯', icon: Newspaper },
    { to: '/digest', label: '简报', icon: Clock },
    { to: '/settings', label: '配置', icon: SlidersHorizontal },
  ]

  const isNavActive = (path: string) => {
    if (path === '/') return location.pathname === '/'
    if (path === '/settings')
      return location.pathname === '/settings' || location.pathname === '/sources'
    return location.pathname === path
  }

  const handleSpotlightTrigger = () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }));
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#eef2f8] text-[#293859]">
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed bottom-7 right-6 z-[60] flex h-14 w-14 items-center justify-center rounded-full bg-[#49A8C9] text-white shadow-lg shadow-[#49A8C9]/35 md:hidden active:scale-95 transition-transform"
      >
        <Menu size={24} strokeWidth={iconStroke} />
      </button>

      <aside className="hidden w-[15rem] flex-col border-r border-white/10 bg-[#293859] px-4 py-7 md:flex">
        <div className="mb-7 flex items-center gap-3.5 px-0.5">
          <div className="flex h-[3.85rem] w-[3.85rem] shrink-0 items-center justify-center rounded-[1.3rem] bg-gradient-to-br from-[#5eb8d4] to-[#3d92b0] shadow-md shadow-[#49A8C9]/25 ring-1 ring-white/15">
            <BookOpen className="h-[28px] w-[28px] text-white" strokeWidth={iconStroke} />
          </div>
          <div className="min-w-0 self-center">
            <div className="flex items-baseline leading-none">
              <span className="text-[28px] font-semibold tracking-[-0.035em] text-[#D1E0E9] sm:text-[28px]">
              P<span className="text-[#7fd4ed]">.</span>I<span className="text-[#7fd4ed]">.</span>M
              </span>
            </div>
            <p className="mt-1 text-[13px] font-medium tracking-[-0.01em] text-[#8a9eb3]">你的个人资讯助理</p>
          </div>
        </div>

        <div className="flex-1">
          <nav className="rounded-[1.65rem] border border-white/[0.08] bg-white/[0.032] p-3">
            <div className="px-1 pb-3">
              <NavSectionLabel />
            </div>
            <div className="space-y-1">
              {navItems.map((item) => (
                <SidebarItem
                  key={item.to}
                  {...item}
                  isActive={isNavActive(item.to)}
                />
              ))}
            </div>
          </nav>
        </div>

        <div className="pt-5">
          <button
            type="button"
            onClick={handleSpotlightTrigger}
            className="group flex w-full items-center justify-between rounded-[1.3rem] border border-white/[0.08] bg-white/[0.032] px-3.5 py-3 text-left transition-all hover:border-white/[0.12] hover:bg-white/[0.05]"
          >
            <div className="flex items-center gap-3">
              <span className="flex h-9.5 w-9.5 items-center justify-center rounded-[0.95rem] border border-white/[0.08] bg-white/[0.035] text-[#8ea3b8] transition-colors group-hover:text-[#7fd4ed]">
                <Search size={16} strokeWidth={iconStroke} />
              </span>
              <span className="text-[14px] font-medium tracking-[-0.01em] text-[#c5d6e3] group-hover:text-[#D1E0E9]">快速搜索</span>
            </div>
            <div className="flex items-center gap-1 rounded-full border border-white/[0.08] bg-[#24324d] px-2.5 py-1 text-[12px] font-semibold tracking-tight text-[#8a9eb3]">
              <Command size={10} />
              <span>K</span>
            </div>
          </button>
        </div>
      </aside>

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-[100] bg-[#293859]/55 backdrop-blur-sm md:hidden"
            />
            <motion.aside
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 220 }}
              className="fixed inset-y-0 left-0 z-[110] w-[15rem] bg-[#293859] px-4 py-7 md:hidden shadow-2xl"
            >
              <div className="mb-6 flex items-center justify-between gap-3 px-1">
                <NavSectionLabel />
                <button
                  type="button"
                  onClick={() => setMobileOpen(false)}
                  className="rounded-lg p-2 text-[#a8bfcf] hover:bg-white/5 hover:text-white"
                >
                  <X size={22} strokeWidth={iconStroke} />
                </button>
              </div>
              <nav className="rounded-[1.75rem] border border-white/[0.08] bg-white/[0.032] p-3">
                <div className="space-y-1.5">
                {navItems.map((item) => (
                  <SidebarItem
                    key={item.to}
                    {...item}
                    isActive={isNavActive(item.to)}
                    onClick={() => setMobileOpen(false)}
                  />
                ))}
                </div>
              </nav>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <main className="relative flex-1 overflow-y-auto overflow-x-hidden scroll-smooth bg-[#f5f9fc] shadow-[inset_1px_0_0_rgba(88,100,118,0.06)]">
        {children}
      </main>
    </div>
  );
};

export default MainLayout;
