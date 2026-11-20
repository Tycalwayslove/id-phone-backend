import { Alert, Button, Checkbox, Descriptions, Modal, Space } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from './confirm'
import { DataTable } from './ui'

type Provider = Pick<Schema['AdminProviderOut'], 'code' | 'name'>
type SyncResult = Schema['ProviderSyncResult']

/** 从服务商同步规格目录：确认 → 调接口 → 刷新规格与服务商数据 → 弹出结果。服务商页和规格页共用。 */
export function useSpecSync() {
  const confirm = useConfirmChange('providers')
  const cache = useQueryClient()
  const [syncing, setSyncing] = useState<string>()
  const [report, setReport] = useState<{ providerName: string; autoPublish: boolean; result: SyncResult }>()

  function sync(provider: Provider) {
    let autoPublish = true
    confirm({
      title: '同步规格',
      content: (
        <Space direction="vertical">
          <span>从「{provider.name}」同步规格目录？同步会更新制照参数，并停用目录中已移除的规格映射。</span>
          <Checkbox defaultChecked onChange={(event) => { autoPublish = event.target.checked }}>同步后自动上架</Checkbox>
        </Space>
      ),
      okText: '确认同步',
    }, async () => {
      const publish = autoPublish
      setSyncing(provider.code)
      try {
        const result = await adminApi.syncProviderSpecs(provider.code, publish)
        setReport({ providerName: provider.name, autoPublish: publish, result })
      } finally {
        setSyncing(undefined)
        void cache.invalidateQueries({ queryKey: ['specs'] })
      }
    }, '规格已同步')
  }

  const close = () => setReport(undefined)
  const details = report?.result.items.filter(({ change, unknown_receipt_fields }) =>
    change === 'created' || !!unknown_receipt_fields?.length)
  const reportModal = report && (
    <Modal open title={`${report.providerName}规格同步结果`} width={620} onCancel={close}
      footer={<Button type="primary" onClick={close}>关闭</Button>}>
      <Descriptions size="small" column={2} items={[
        { key: 'created', label: '新增映射', children: report.result.created },
        { key: 'updated', label: '更新', children: report.result.updated },
        { key: 'unchanged', label: '未变', children: report.result.unchanged },
        { key: 'disabled', label: '停用', children: report.result.disabled },
      ]} />
      {report.result.created > 0 && <Alert className="detail-note" type="info" showIcon message={report.autoPublish
        ? '新规格已上架，新映射已启用。可在服务商页补充办理成本。'
        : '新规格已下架，新映射已停用。审核后可上架规格，并配置映射及路由规则。'} />}
      {!!details?.length && (
        <DataTable<Schema['ProviderSyncItem']>
          rowKey="spec_code"
          dataSource={details}
          columns={[
            { title: '规格', dataIndex: 'spec_name' },
            { title: '规格编码', dataIndex: 'spec_code' },
            { title: '未识别回执字段', render: (_, row) => row.unknown_receipt_fields?.join('、') || '—' },
          ]}
          scroll={{ y: 320 }}
        />
      )}
    </Modal>
  )

  return { sync, syncing, reportModal }
}
