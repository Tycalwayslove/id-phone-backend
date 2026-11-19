import { Avatar, Descriptions, Drawer, Form, Select, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, useMatch, useNavigate } from 'react-router-dom'
import { adminApi, type UserFilters } from '../api/admin'
import { type Schema } from '../api/client'
import { CursorTable, FilterForm, IdFilter, Loading, PageHeading, Problem, Status, TextFilter, useCursorList, useFilters } from '../components/ui'
import { dateText, enumOptions, identitySources, labelFor, money, userStatus } from '../format'

function UserDetail({ userId }: { userId: number }) {
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
        { label: '已支付订单数', children: user.orders_count },
        { label: '累计实付', children: money(user.paid_fen_total) },
        { label: '回执申请数', children: user.applications_count },
        { label: '注册时间', children: dateText(user.created_at) },
        { label: '最近活跃', children: dateText(user.last_active_at) },
      ]} />
    </>
  )
}

export default function Users() {
  const search = useFilters<UserFilters>()
  const query = useCursorList('users', (cursor, signal) => adminApi.users({ ...search.filters, cursor }, signal), search.version)
  const match = useMatch('/users/:userId')
  const userId = Number(match?.params.userId)
  const navigate = useNavigate()

  return (
    <>
      <PageHeading title="用户" />
      <FilterForm<UserFilters> onFinish={(values) => search.apply({ ...values, phone: values.phone?.trim() || undefined })}>
        <IdFilter />
        <TextFilter label="完整手机号" name="phone" minLength={5} maxLength={20} />
        <Form.Item label="账号状态" name="status">
          <Select allowClear className="filter-select" options={enumOptions(userStatus)} />
        </Form.Item>
      </FilterForm>
      <CursorTable<Schema['AdminUserOut']> query={query} rowKey="id" columns={[
        { title: '用户 ID', dataIndex: 'id', render: (id: number) => <Link to={`/users/${id}`}>{id}</Link> },
        { title: '昵称', dataIndex: 'nickname', render: (value: string | null) => value || '—' },
        { title: '手机号', dataIndex: 'phone_masked', render: (value: string | null) => value ?? '—' },
        { title: '状态', render: (_, user) => <Status value={user.status} labels={userStatus} /> },
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
