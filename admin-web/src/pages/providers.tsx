import { PlusOutlined } from '@ant-design/icons'
import { Button, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { DataTable, PageHeading, Problem, Section, Status } from '../components/ui'
import { dateText, money, providerStatus } from '../format'
import { usePermission } from '../session'
import { ProviderSpecEditor, RouteRuleEditor } from './provider-editors'

type Provider = Schema['AdminProviderOut']
type ProviderSpec = Schema['AdminProviderSpecOut']
type RouteRule = Schema['AdminRouteRuleOut']
type Edit =
  | { type: 'spec'; providerCode: string; entry: ProviderSpec | null }
  | { type: 'rule'; providerCode: string; rule: RouteRule | null }
const stateChanges = [
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
  { value: 'circuit_open', label: '熔断' },
] satisfies { value: Provider['status']; label: string }[]

function ProviderDetails({ provider, edit, busy }: { provider: Provider; edit?: (value: Edit) => void; busy: boolean }) {
  const confirm = useConfirmChange('providers')
  return (
    <>
      <Section title="支持的规格" action={edit && (
        <Button size="small" icon={<PlusOutlined />} disabled={busy}
          onClick={() => edit({ type: 'spec', providerCode: provider.code, entry: null })}>新增规格</Button>
      )}>
        <DataTable<ProviderSpec> rowKey="id" dataSource={provider.provider_specs} columns={[
          { title: '规格', dataIndex: 'spec_name' },
          { title: '规格编码', dataIndex: 'spec_code' },
          { title: '服务商规格 ID', dataIndex: 'provider_item_id' },
          { title: '办理成本', dataIndex: 'cost_fen', render: money, className: 'amount', align: 'right' },
          { title: '状态', render: (_, row) => row.is_enabled ? '启用' : '停用' },
          { title: '最近同步', dataIndex: 'last_synced_at', render: dateText },
          ...(edit ? [{
            title: '操作',
            render: (_: unknown, entry: ProviderSpec) => (
              <Space>
                <Button size="small" disabled={busy} onClick={() => edit({ type: 'spec', providerCode: provider.code, entry })}>编辑</Button>
                <Button size="small" danger disabled={busy} onClick={() => confirm({
                  title: '删除服务商规格',
                  content: `删除「${provider.name}」的「${entry.spec_name}」配置后，相关路由将无法匹配此配置。`,
                  okText: '确认删除',
                  okType: 'danger',
                }, () => adminApi.deleteProviderSpec(entry.id), '已删除服务商规格')}>删除</Button>
              </Space>
            ),
          }] : []),
        ]} />
      </Section>
      <Section title="路由规则" action={edit && (
        <Button size="small" icon={<PlusOutlined />} disabled={busy}
          onClick={() => edit({ type: 'rule', providerCode: provider.code, rule: null })}>新增规则</Button>
      )}>
        <DataTable<RouteRule>
          rowKey="id"
          dataSource={provider.route_rules}
          columns={[
            { title: '规格编码', dataIndex: 'spec_code' },
            { title: '地区码', render: (_, row) => row.region_code ?? '不限' },
            { title: '优先级（数字越小越优先）', dataIndex: 'priority', align: 'right' },
            { title: '状态', render: (_, row) => row.is_enabled ? '启用' : '停用' },
            ...(edit ? [{
              title: '操作',
              render: (_: unknown, rule: RouteRule) => (
                <Space>
                  <Button size="small" disabled={busy} onClick={() => edit({ type: 'rule', providerCode: provider.code, rule })}>编辑</Button>
                  <Button size="small" danger disabled={busy} onClick={() => confirm({
                    title: '删除路由规则',
                    content: `确认删除「${provider.name}」的 ${rule.spec_code} 路由规则（${rule.region_code ?? '不限地区'}）？`,
                    okText: '确认删除',
                    okType: 'danger',
                  }, () => adminApi.deleteRouteRule(rule.id), '已删除路由规则')}>删除</Button>
                </Space>
              ),
            }] : []),
          ]}
        />
      </Section>
    </>
  )
}

export default function Providers() {
  const canWrite = usePermission('provider:write')
  const confirm = useConfirmChange('providers')
  const [editing, setEditing] = useState<Edit>()
  const query = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => adminApi.providers(signal) })
  const providerOptions = (query.data ?? []).map(({ code, name }) => ({ value: code, label: `${name}（${code}）` }))
  const closeEditor = () => setEditing(undefined)

  return (
    <>
      <PageHeading title="服务商" />
      <div className="data-surface">
        {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
        <DataTable<Provider> rowKey="code" loading={query.isPending} dataSource={query.data} expandable={{
          expandedRowRender: (provider) => (
            <ProviderDetails provider={provider} edit={canWrite ? setEditing : undefined} busy={query.isFetching} />
          ),
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
      {canWrite && editing?.type === 'spec' && (
        <ProviderSpecEditor providerCode={editing.providerCode} providerOptions={providerOptions} entry={editing.entry} onClose={closeEditor} />
      )}
      {canWrite && editing?.type === 'rule' && (
        <RouteRuleEditor providerCode={editing.providerCode} providerOptions={providerOptions} rule={editing.rule} onClose={closeEditor} />
      )}
    </>
  )
}
