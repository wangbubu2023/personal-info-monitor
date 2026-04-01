import React, { useState, useEffect } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { SearchOutlined, MenuOutlined, CloseOutlined } from '@ant-design/icons'

interface NavItem {
  path: string
  label: string
}

const navItems: NavItem[] = [
  { path: '/', label: '首页' },
  { path: '/digest', label: '私人简报' },
  { path: '/settings', label: '设置' },
]

const Header: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Sync search input with URL search param
  useEffect(() => {
    const urlSearch = searchParams.get('search') || ''
    if (location.pathname === '/' && urlSearch) {
      setSearchQuery(urlSearch)
    }
  }, [searchParams, location.pathname])

  const handleSearch = () => {
    const q = searchQuery.trim()
    if (q) {
      navigate(`/?search=${encodeURIComponent(q)}`)
    } else {
      // Clear search, go to home
      navigate('/')
    }
  }

  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 100 }} data-testid="app-header">
      {/* 顶部栏 - Logo + 搜索 */}
      <div style={{
        backgroundColor: '#fff',
        borderBottom: '1px solid #eee',
        padding: '12px 0',
      }}>
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          {/* Logo */}
          <Link to="/" style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontWeight: 600,
            fontSize: 20,
            color: '#333',
            textDecoration: 'none',
          }}>
            <span style={{
              fontSize: 24,
              fontStyle: 'italic',
              fontWeight: 300,
              letterSpacing: -1,
            }}>
              info<span style={{ fontWeight: 600 }}>monitor</span>
            </span>
          </Link>

          {/* 搜索框 - 桌面端 */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
          }}>
            <div style={{ position: 'relative' }} className="search-desktop">
              <input
                data-testid="global-search-input"
                type="text"
                placeholder="搜索内容..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSearch()
                }}
                style={{
                  width: 240,
                  padding: '8px 36px 8px 12px',
                  border: '1px solid #ddd',
                  borderRadius: 4,
                  fontSize: 14,
                  outline: 'none',
                }}
              />
              <SearchOutlined
                onClick={handleSearch}
                style={{
                  position: 'absolute',
                  right: 12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: '#999',
                  cursor: 'pointer',
                }}
              />
            </div>

            {/* 移动端菜单按钮 */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="mobile-menu-btn"
              style={{
                padding: 8,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: 20,
              }}
            >
              {mobileMenuOpen ? <CloseOutlined /> : <MenuOutlined />}
            </button>
          </div>
        </div>
      </div>

      {/* 导航栏 - 绿色背景 */}
      <nav style={{ backgroundColor: '#6b7c3f' }} data-testid="global-nav">
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
        }}>
          {navItems.map((item) => {
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                data-testid={`global-nav-${item.path === '/' ? 'home' : item.path.slice(1)}`}
                style={{
                  padding: '12px 20px',
                  color: '#fff',
                  fontSize: 14,
                  fontWeight: 500,
                  backgroundColor: isActive ? 'rgba(0,0,0,0.15)' : 'transparent',
                  transition: 'background-color 0.2s',
                  textDecoration: 'none',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.1)'
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                {item.label}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* 移动端菜单 */}
      {mobileMenuOpen && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          right: 0,
          backgroundColor: '#fff',
          borderBottom: '1px solid #eee',
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
        }}>
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => setMobileMenuOpen(false)}
              style={{
                display: 'block',
                padding: '14px 24px',
                color: location.pathname === item.path ? '#6b7c3f' : '#333',
                borderBottom: '1px solid #f0f0f0',
                fontWeight: location.pathname === item.path ? 600 : 400,
                textDecoration: 'none',
              }}
            >
              {item.label}
            </Link>
          ))}
        </div>
      )}

      <style>{`
        @media (min-width: 768px) {
          .search-desktop { display: block !important; }
          .mobile-menu-btn { display: none !important; }
        }
        @media (max-width: 767px) {
          .search-desktop { display: none !important; }
          .mobile-menu-btn { display: block !important; }
        }
      `}</style>
    </header>
  )
}

export default Header
