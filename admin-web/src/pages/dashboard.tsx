import { Card, Statistic } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import { DataTable, Loading, PageHeading, Problem, Section, Status } from '../components/ui'
import { enumOptions, money, receiptStatus } from '../format'

function DashboardData() {
  const query = useQuery({ queryKey: ['stats', 'overview'], queryFn: ({ signal }) => adminApi.statsOverview(signal) })
  if (query.isError) return <Problem error={query.error} retry={() => { void query.refetch() }} />
  if (!query.data) return <Loading />
  const stats = query.data
  const receiptCounts = enumOptions(receiptStatus).map(({ value }) => ({
    status: value, count: stats.receipt_counts_by_status[value] ?? 0,
  }))

  return (
    <>
      <div className="dashboard-metrics">
        <Card><Statistic title="用户数" value={stats.user_count} /></Card>
        <Card><Statistic title="订单数" value={stats.order_count} /></Card>
        <Card><Statistic title="实付总额（元，含已退款金额）" value={money(stats.paid_total_fen)} /></Card>
      </div>
      <Section title="回执申请">
        <div className="data-surface">
          <DataTable rowKey="status" dataSource={receiptCounts} columns={[
            { title: '状态', render: (_, row) => <Status value={row.status} labels={receiptStatus} /> },
            { title: '数量', dataIndex: 'count', align: 'right' },
          ]} />
        </div>
      </Section>
    </>
  )
}

export default function Dashboard() {
  return (
    <>
      <PageHeading title="数据看板" />
      <DashboardData />
    </>
  )
}
