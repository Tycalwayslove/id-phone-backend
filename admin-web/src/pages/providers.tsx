import { Button, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { DataTable, PageHeading, Problem, Section, Status } from '../components/ui'
import { dateText, money, providerStatus } from '../format'
import { usePermission } from '../session'

type Provider = Schema['AdminProviderOut']
const stateChanges = [
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
  { value: 'circuit_open', label: '熔断' },
] satisfies { value: Provider['status']; label: string }[]

function ProviderDetails({ provider }: { provider: Provider }) {
  return (
    <>
      <Section title="支持的规格">
        <DataTable<Schema['AdminProviderSpecOut']> rowKey="spec_code" dataSource={provider.provider_specs} columns={[
          { title: '规格', dataIndex: 'spec_name' },
          { title: '规格编码', dataIndex: 'spec_code' },
          { title: '服务商规格 ID', dataIndex: 'provider_item_id' },
          { title: '办理成本', dataIndex: 'cost_fen', render: money, className: 'amount', align: 'right' },
          { title: '状态', render: (_, row) => row.is_enabled ? '启用' : '停用' },
          { title: '最近同步', dataIndex: 'last_synced_at', render: dateText },
        ]} />
      </Section>
      <Section title="路由规则">
        <DataTable<Schema['AdminRouteRuleOut']>
          rowKey={(rule) => `${rule.spec_code}/${rule.region_code ?? ''}/${rule.priority}`}
          dataSource={provider.route_rules}
          columns={[
            { title: '规格编码', dataIndex: 'spec_code' },
            { title: '地区码', render: (_, row) => row.region_code ?? '不限' },
            { title: '优先级（数字越小越优先）', dataIndex: 'priority', align: 'right' },
            { title: '状态', render: (_, row) => row.is_enabled ? '启用' : '停用' },
          ]}
        />
      </Section>
    </>
  )
}

export default function Providers() {
  const canWrite = usePermission('provider:write')
  const confirm = useConfirmChange('providers')
  const query = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => adminApi.providers(signal) })

  return (
    <>
      <PageHeading title="服务商" />
      <div className="data-surface">
        {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
        <DataTable<Provider> rowKey="code" loading={query.isPending} dataSource={query.data} expandable={{
          expandedRowRender: (provider) => <ProviderDetails provider={provider} />,
        }} columns={[
          { title: '服务商', dataIndex: 'name' },
          { title: '编码', dataIndex: 'code' },
          { title: '适配器', dataIndex: 'adapter' },
          { title: '上游分组', render: (_, row) => row.upstream_group ?? '—' },
          { title: '状态', render: (_, row) => <Status value={row.status} labels={providerStatus} /> },
          { title: '支持规格数', render: (_, row) => row.provider_specs.length, align: 'right' },
          { title: '最近修改', dataIndex: 'updated_at', render: dateText },
          ...(canWrite ? [{
            title: '操作',
            render: (_: unknown, row: Provider) => (
              <Space>
                {stateChanges.filter((change) => change.value !== row.status).map(({ value, label }) => (
                  <Button key={value} size="small" danger={value !== 'enabled'} disabled={query.isFetching}
                    onClick={() => confirm({
                      title: `${label}服务商`,
                      content: value === 'enabled'
                        ? `${row.name} 将恢复参与新单路由。`
                        : `${row.name} 将暂停接收新单。`,
                      okText: `确认${label}`,
                      okType: value === 'enabled' ? 'primary' : 'danger',
                    }, () => adminApi.updateProvider(row.code, { status: value }), '服务商状态已更新')}
                  >{label}</Button>
                ))}
              </Space>
            ),
          }] : []),
        ]} />
      </div>
    </>
  )
}
