import { Form, Select } from 'antd'
import { adminApi, type NotifyFilters } from '../api/admin'
import type { Schema } from '../api/client'
import { PagedTable, FilterForm, PageHeading, Status, usePagedList } from '../components/ui'
import { dateText, enumOptions, notifyChannel, notifyEvent, notifyStatus } from '../format'

type NotifyTask = Schema['AdminNotifyTaskOut']
type Filters = Pick<NotifyFilters, 'status'>

export default function Notifications() {
  const query = usePagedList('notify-tasks', adminApi.notifyTasks, {} satisfies Filters)

  return (
    <>
      <PageHeading title="通知任务" />
      <FilterForm<Filters> onFinish={query.apply}>
        <Form.Item label="任务状态" name="status">
          <Select className="filter-select" allowClear options={enumOptions(notifyStatus)} />
        </Form.Item>
      </FilterForm>
      <PagedTable<NotifyTask> query={query} rowKey="id" columns={[
        { title: '任务 ID', dataIndex: 'id' },
        { title: '用户 ID', dataIndex: 'user_id' },
        { title: '事件', render: (_, row) => notifyEvent[row.event] },
        { title: '档位', dataIndex: 'step' },
        { title: '渠道', render: (_, row) => notifyChannel[row.channel] },
        { title: '状态', render: (_, row) => <Status value={row.status} labels={notifyStatus} /> },
        { title: '回执申请 ID', render: (_, row) => row.application_id ?? '—' },
        { title: '权益 ID', render: (_, row) => row.entitlement_id ?? '—' },
        { title: '计划发送时间', dataIndex: 'scheduled_at', render: dateText },
        { title: '实际发送时间', dataIndex: 'sent_at', render: dateText },
        { title: '创建时间', dataIndex: 'created_at', render: dateText },
      ]} />
    </>
  )
}
