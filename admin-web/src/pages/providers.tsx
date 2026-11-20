import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Descriptions, Modal, Space } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
type SyncResult = Schema['ProviderSyncResult']
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
  const cache = useQueryClient()
  const [editing, setEditing] = useState<Edit>()
  const [syncing, setSyncing] = useState<string>()
  const [syncReport, setSyncReport] = useState<{ providerName: string; result: SyncResult }>()
  const query = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => adminApi.providers(signal) })
  const providerOptions = (query.data ?? []).map(({ code, name }) => ({ value: code, label: `${name}（${code}）` }))
  const closeEditor = () => setEditing(undefined)

  function syncSpecs(provider: Provider) {
    confirm({
      title: '同步规格',
      content: `从「${provider.name}」同步规格目录？同步会更新制照参数，并停用目录中已移除的规格映射。`,
      okText: '确认同步',
    }, async () => {
      setSyncing(provider.code)
      try {
        const result = await adminApi.syncProviderSpecs(provider.code)
        setSyncReport({ providerName: provider.name, result })
        void cache.invalidateQueries({ queryKey: ['specs'] })
      } finally {
        setSyncing(undefined)
      }
    }, '规格已同步')
  }

  return (
    <>
      <PageHeading title="服务商" />
      <div className="data-surface">
        {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
        <DataTable<Provider> rowKey="code" loading={query.isPending} dataSource={query.data} expandable={{
          expandedRowRender: (provider) => (
            <ProviderDetails provider={provider} edit={canWrite ? setEditing : undefined} busy={query.isFetching || syncing !== undefined} />
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
                <Button size="small" loading={syncing === row.code} disabled={query.isFetching || syncing !== undefined}
                  onClick={() => syncSpecs(row)}>同步规格</Button>
                {stateChanges.filter((change) => change.value !== row.status).map(({ value, label }) => (
                  <Button key={value} size="small" danger={value !== 'enabled'} disabled={query.isFetching || syncing !== undefined}
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
      {canWrite && syncReport && (
        <Modal open title={`${syncReport.providerName}规格同步结果`} width={620}
          onCancel={() => setSyncReport(undefined)}
          footer={<Button type="primary" onClick={() => setSyncReport(undefined)}>关闭</Button>}>
          <Descriptions size="small" column={2} items={[
            { key: 'created', label: '新增', children: syncReport.result.created },
            { key: 'updated', label: '更新', children: syncReport.result.updated },
            { key: 'unchanged', label: '未变', children: syncReport.result.unchanged },
            { key: 'disabled', label: '停用', children: syncReport.result.disabled },
          ]} />
          <Alert className="detail-note" type="info" showIcon message="新规格默认下架，请在规格页审核后上架" />
          {syncReport.result.created > 0 && (
            <DataTable<Schema['ProviderSyncItem']>
              rowKey="spec_code"
              dataSource={syncReport.result.items.filter(({ change }) => change === 'created')}
              columns={[
                { title: '新增规格', dataIndex: 'spec_name' },
                { title: '规格编码', dataIndex: 'spec_code' },
              ]}
              scroll={{ y: 320 }}
            />
          )}
        </Modal>
      )}
    </>
  )
}
