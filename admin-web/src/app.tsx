import {
  AuditOutlined, FileImageOutlined, FileProtectOutlined, IdcardOutlined, LogoutOutlined,
  ProfileOutlined, ShoppingOutlined, TeamOutlined, PartitionOutlined,
} from '@ant-design/icons'
import { Alert, App as AntApp, Button, Layout, Menu, Result, Space, Tag } from 'antd'
import { lazy, Suspense, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { csrfToken, errorText } from './api/client'
import { Loading, Problem } from './components/ui'
import { adminRole } from './format'
import Login from './pages/login'
import { useSession } from './session'

const pages = [
  { path: '/users', label: '用户', permission: 'user:read', icon: TeamOutlined, Page: lazy(() => import('./pages/users')) },
  { path: '/orders', label: '订单', permission: 'order:read', icon: ShoppingOutlined, Page: lazy(() => import('./pages/orders')) },
  { path: '/receipts', label: '回执', permission: 'application:read', icon: FileProtectOutlined, Page: lazy(() => import('./pages/receipts')) },
  { path: '/plans', label: '套餐', permission: 'plan:read', icon: ProfileOutlined, Page: lazy(() => import('./pages/plans')) },
  { path: '/specs', label: '规格', permission: 'spec:read', icon: FileImageOutlined, Page: lazy(() => import('./pages/specs')) },
  { path: '/providers', label: '服务商', permission: 'provider:read', icon: PartitionOutlined, Page: lazy(() => import('./pages/providers')) },
  { path: '/audit', label: '审计日志', permission: 'audit:read', icon: AuditOutlined, Page: lazy(() => import('./pages/audit')) },
]

export function App() {
  const { state, check, logout } = useSession()
  const location = useLocation()
  const { message } = AntApp.useApp()
  const [signingOut, setSigningOut] = useState(false)

  if (state.status === 'checking') return <Loading />
  if (state.status === 'failed') return <main className="session-problem"><Problem error={state.error} retry={check} /></main>
  if (state.status === 'anonymous') {
    return location.pathname === '/login'
      ? <Login />
      : <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  const account = state.account
  const visible = pages.filter((page) => account.permissions.includes(page.permission))
  const first = visible[0]?.path
  if (location.pathname === '/login') {
    const from: unknown = location.state?.from
    const permitted = typeof from === 'string' && visible.some((page) => from === page.path || from.startsWith(`${page.path}/`))
    return <Navigate to={permitted ? from : first ?? '/'} replace />
  }
  const selected = pages.find((page) => location.pathname === page.path || location.pathname.startsWith(`${page.path}/`))

  async function signOut() {
    setSigningOut(true)
    try {
      await logout()
    } catch (error) {
      void message.error(errorText(error))
    } finally {
      setSigningOut(false)
    }
  }

  return (
    <Layout className="app-shell">
      <Layout.Sider width={216} breakpoint="md" collapsedWidth={60} theme="light" className="sidebar">
        <div className="brand">
          <span className="brand-icon"><IdcardOutlined /></span>
          <div className="brand-copy"><strong>智拍证件照</strong><span>运营后台</span></div>
        </div>
        <nav aria-label="后台导航">
          <Menu mode="inline" selectedKeys={selected ? [selected.path] : []} items={visible.map((page) => ({
            key: page.path, icon: <page.icon />, label: <Link to={page.path}>{page.label}</Link>, title: page.label,
          }))} />
        </nav>
      </Layout.Sider>
      <Layout className="workspace">
        <Layout.Header className="account-bar">
          <Space size={8} wrap><span className="account-name">{account.username}</span><Tag>{adminRole[account.role]}</Tag></Space>
          <Button type="text" icon={<LogoutOutlined />} loading={signingOut} onClick={() => { void signOut() }}>退出登录</Button>
        </Layout.Header>
        <Layout.Content className="workspace-content">
          {!csrfToken() && <Alert type="warning" showIcon message="此标签页缺少修改操作所需的会话验证。如需修改，请退出后重新登录。" />}
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={first ? <Navigate to={first} replace /> : <Result status="403" title="当前账号没有可访问的页面" />} />
              {pages.map(({ path, permission, Page }) => (
                <Route key={path} path={`${path}/*`} element={account.permissions.includes(permission)
                  ? <Page />
                  : <Result status="403" title="无权限访问此页面" />}
                />
              ))}
              <Route path="*" element={<Result status="404" title="页面不存在" extra={first && <Link to={first}>返回后台</Link>} />} />
            </Routes>
          </Suspense>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
