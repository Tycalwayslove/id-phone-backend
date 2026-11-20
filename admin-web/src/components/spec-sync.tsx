import { Alert, Button, Descriptions, Modal } from 'antd'
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
  const [report, setReport] = useState<{ providerName: string; result: SyncResult }>()

  function sync(provider: Provider) {
    confirm({
      title: '同步规格',
      content: `从「${provider.name}」同步规格目录？同步会更新制照参数，并停用目录中已移除的规格映射。`,
      okText: '确认同步',
    }, async () => {
      setSyncing(provider.code)
      try {
        const result = await adminApi.syncProviderSpecs(provider.code)
        setReport({ providerName: provider.name, result })
      } finally {
        setSyncing(undefined)
        void cache.invalidateQueries({ queryKey: ['specs'] })
      }
    }, '规格已同步')
  }

  const close = () => setReport(undefined)
  const reportModal = report && (
    <Modal open title={`${report.providerName}规格同步结果`} width={620} onCancel={close}
      footer={<Button type="primary" onClick={close}>关闭</Button>}>
      <Descriptions size="small" column={2} items={[
        { key: 'created', label: '新增', children: report.result.created },
        { key: 'updated', label: '更新', children: report.result.updated },
        { key: 'unchanged', label: '未变', children: report.result.unchanged },
        { key: 'disabled', label: '停用', children: report.result.disabled },
      ]} />
      <Alert className="detail-note" type="info" showIcon
        message="新规格默认下架、服务商映射默认停用：请在规格页筛选“下架”审核后上架，并在服务商页配置成本后启用映射" />
      {report.result.created > 0 && (
        <DataTable<Schema['ProviderSyncItem']>
          rowKey="spec_code"
          dataSource={report.result.items.filter(({ change }) => change === 'created')}
          columns={[
            { title: '新增规格', dataIndex: 'spec_name' },
            { title: '规格编码', dataIndex: 'spec_code' },
          ]}
          scroll={{ y: 320 }}
        />
      )}
    </Modal>
  )

  return { sync, syncing, reportModal }
}
