import { Avatar, Descriptions, Drawer, Form, Select, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, useMatch, useNavigate } from 'react-router-dom'
import { adminApi, type UserFilters } from '../api/admin'
import { type Schema } from '../api/client'
import { PhotoGallery } from '../components/photo-gallery'
import { CursorTable, FilterForm, IdFilter, Loading, PageHeading, Problem, Section, Status, TextFilter, useCursorList, useFilters } from '../components/ui'
import { clientAppPlatforms, dateText, enumOptions, identitySources, labelFor, money, userStatus } from '../format'
import { usePermission } from '../session'

type ClientApp = Schema['AdminClientAppOut']

async function fetchAppOptions(signal: AbortSignal) {
  const apps: ClientApp[] = []
  let cursor: string | null = null
  do {
    const page = await adminApi.clientApps({ cursor, limit: 100 }, signal)
    apps.push(...page.items)
    cursor = page.next_cursor ?? null
  } while (cursor)
  return apps
}

function UserDetail({ userId }: { userId: number }) {
  const canViewPhotos = usePermission('photo:read')
  const query = useQuery({
    queryKey: ['users', 'detail', userId],
    queryFn: ({ signal }) => adminApi.user(userId, signal),
  })
  if (query.isError) return <Problem error={query.error} retry={() => { void query.refetch() }} />
  if (!query.data) return <Loading />
  const user = query.data

  return (
    <>
      <Space className="detail-note"><Avatar src={user.avatar_url}>{user.nickname?.[0] ?? '用'}</Avatar><strong>{user.nickname || '未设置昵称'}</strong></Space>
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
        { label: '用户 ID', children: user.id },
        { label: '账号状态', children: <Status value={user.status} labels={userStatus} /> },
        { label: '手机号', children: user.phone_masked ?? '—' },
        { label: '登录身份', children: user.identities.length
          ? user.identities.map((identity) => <Tag key={identity}>{labelFor(identitySources, identity)}</Tag>) : '—' },
        { label: '来源应用', children: user.source_app
          ? `${user.source_app.name}（${clientAppPlatforms[user.source_app.platform]}）` : '—' },
        { label: 'AppID', children: user.source_app?.app_id ?? '—' },
        { label: '首次渠道', children: user.first_channel_name ?? '—' },
        { label: '已支付订单数', children: user.orders_count },
        { label: '累计实付', children: money(user.paid_fen_total) },
        { label: '回执申请数', children: user.applications_count },
        { label: '注册时间', children: dateText(user.created_at) },
        { label: '最近活跃', children: dateText(user.last_active_at) },
      ]} />
      {canViewPhotos && (
        <Section title="照片" action={<Link to={`/photos?user_id=${user.id}`}>查看全部</Link>}>
          <PhotoGallery photos={user.recent_photos} />
        </Section>
      )}
    </>
  )
}

export default function Users() {
  const search = useFilters<UserFilters>()
  const query = useCursorList('users', (cursor, signal) => adminApi.users({ ...search.filters, cursor }, signal), search.version)
  const apps = useQuery({ queryKey: ['client-apps', 'options'], queryFn: ({ signal }) => fetchAppOptions(signal) })
  const match = useMatch('/users/:userId')
  const userId = Number(match?.params.userId)
  const navigate = useNavigate()

  return (
    <>
      <PageHeading title="用户" />
      {apps.isError && <Problem error={apps.error} retry={() => { void apps.refetch() }} />}
      <FilterForm<UserFilters> onFinish={(values) => search.apply({ ...values, phone: values.phone?.trim() || undefined })}>
        <IdFilter />
        <TextFilter label="完整手机号" name="phone" minLength={5} maxLength={20} />
        <Form.Item label="账号状态" name="status">
          <Select allowClear className="filter-select" options={enumOptions(userStatus)} />
        </Form.Item>
        <Form.Item label="来源应用" name="source_app_id">
          <Select allowClear showSearch optionFilterProp="label" className="app-source-filter" loading={apps.isPending}
            options={apps.data?.map((app) => ({ value: app.id, label: `${app.name}（${clientAppPlatforms[app.platform]} / ${app.app_id}）` }))} />
        </Form.Item>
      </FilterForm>
      <CursorTable<Schema['AdminUserOut']> query={query} rowKey="id" columns={[
        { title: '用户 ID', dataIndex: 'id', render: (id: number) => <Link to={`/users/${id}`}>{id}</Link> },
        { title: '昵称', dataIndex: 'nickname', render: (value: string | null) => value || '—' },
        { title: '手机号', dataIndex: 'phone_masked', render: (value: string | null) => value ?? '—' },
        { title: '状态', render: (_, user) => <Status value={user.status} labels={userStatus} /> },
        { title: '来源应用', render: (_, user) => user.source_app
          ? <span title={user.source_app.app_id}>{user.source_app.name}（{clientAppPlatforms[user.source_app.platform]}）</span>
          : '—' },
        { title: '已支付订单数', dataIndex: 'orders_count', align: 'right' },
        { title: '累计实付', dataIndex: 'paid_fen_total', align: 'right', className: 'amount', render: money },
        { title: '注册时间', dataIndex: 'created_at', render: dateText },
        { title: '最近活跃', dataIndex: 'last_active_at', render: dateText },
      ]} />
      {match && (
        <Drawer open title="用户详情" width="min(100vw, 660px)" onClose={() => navigate('/users', { replace: true })}>
          {Number.isSafeInteger(userId) && userId > 0
            ? <UserDetail userId={userId} />
            : <p>用户 ID 无效。</p>}
        </Drawer>
      )}
    </>
  )
}
