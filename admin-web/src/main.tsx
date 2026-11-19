import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'antd/dist/reset.css'
import { App } from './app'
import { SessionProvider } from './session'
import './styles.css'

dayjs.locale('zh-cn')

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 15_000 },
    mutations: { retry: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#126758',
          colorText: '#172b2a',
          colorTextSecondary: '#526563',
          colorBorderSecondary: '#e1e9e6',
          borderRadius: 6,
          fontFamily: 'system-ui, "PingFang SC", "Microsoft YaHei", sans-serif',
        },
        components: {
          Table: { headerBg: '#f5f8f7', headerColor: '#435956', rowHoverBg: '#f1f8f5' },
          Menu: { itemSelectedBg: '#dceee7', itemSelectedColor: '#0c5144', itemHeight: 42 },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <SessionProvider><App /></SessionProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
