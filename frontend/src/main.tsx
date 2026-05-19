import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/tailwind.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: theme.defaultAlgorithm,
          token: {
            colorPrimary: '#49A8C9',
            borderRadius: 12,
            colorBgBase: '#f5f9fc',
            colorBgContainer: '#ffffff',
            colorBorder: 'rgba(88, 100, 118, 0.18)',
            colorText: '#293859',
            colorTextSecondary: '#586476',
            fontFamily: '"Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif',
          },
          components: {
            Message: {
              contentBg: '#ffffff',
              colorText: '#293859',
            },
            Spin: {
              colorPrimary: '#49A8C9',
            },
            Tabs: {
              itemActiveColor: '#49A8C9',
              inkBarColor: '#49A8C9',
            },
            DatePicker: {
              activeBg: '#EEF4F8',
              activeBorderColor: '#49A8C9',
            },
          },
        }}
      >
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
