import { Alert, Button, Descriptions, Drawer, Empty, Form, Select, Space, Tag, Timeline } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, useMatch, useNavigate } from 'react-router-dom'
import { adminApi, type ReceiptFilters } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { CursorTable, FilterForm, IdFilter, Loading, PageHeading, Problem, Section, Status, TextFilter, useCursorList, useFilters } from '../components/ui'
import { attemptStatus, dateText, enumOptions, labelFor, money, receiptStatus } from '../format'
import { usePermission } from '../session'

const formLabels = { name: '姓名', id_no: '身份证号', id_card: '身份证号', id_number: '身份证号', phone: '手机号', mobile: '手机号' }

function ReceiptDetail({ appNo }: { appNo: string }) {
  const canCancel = usePermission('application:operate')
  const canReadUsers = usePermission('user:read')
  const confirm = useConfirmChange('receipts')
  const query = useQuery({
    queryKey: ['receipts', 'detail', appNo],
    queryFn: ({ signal }) => adminApi.receipt(appNo, signal),
  })
  if (query.isError) return <Problem error={query.error} retry={() => { void query.refetch() }} />
  if (!query.data) return <Loading />
  const receipt = query.data
  const fields = Object.entries(receipt.form_masked)

  return (
    <>
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
        { label: '申请单号', children: receipt.app_no },
        { label: '状态', children: <Status value={receipt.status} labels={receiptStatus} /> },
        { label: '用户 ID', children: canReadUsers ? <Link to={`/users/${receipt.user_id}`}>{receipt.user_id}</Link> : receipt.user_id },
        { label: '规格', children: `${receipt.spec_name}（${receipt.spec_code}）` },
        { label: '地区码', children: receipt.region_code ?? '不限' },
        { label: '照片 ID', children: receipt.photo_id },
        { label: '权益 ID', children: receipt.entitlement_id },
        { label: '重提次数', children: receipt.resubmit_count },
        { label: '回执图像号', children: receipt.image_code ?? '—' },
        { label: '创建时间', children: dateText(receipt.created_at) },
        { label: '最近更新', children: dateText(receipt.updated_at) },
        { label: '驳回时间', children: dateText(receipt.rejected_at) },
        { label: '出回执时间', children: dateText(receipt.completed_at) },
        { label: '官方有效期截止', children: dateText(receipt.official_expire_at) },
      ]} />
      {receipt.reject_reason && <Alert className="detail-note" type="warning" showIcon message="当前驳回原因" description={receipt.reject_reason} />}
      {canCancel && (receipt.status === 'pending' || receipt.status === 'rejected') && (
        <Button className="detail-note" danger disabled={query.isFetching} onClick={() => confirm({
          title: '取消回执办理',
          content: `取消申请 ${receipt.app_no} 后，将退还已占用的回执次数。`,
          okText: '确认取消办理',
          okType: 'danger',
        }, () => adminApi.cancelReceipt(receipt.app_no), '已取消办理')}>取消办理</Button>
      )}
      <Section title="脱敏表单">
        {fields.length ? <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={fields.map(([key, value]) => ({
          key, label: labelFor(formLabels, key), children: value || '—',
        }))} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无表单数据" />}
      </Section>
      <Section title="提交记录">
        {receipt.attempts.length
          ? <Timeline items={receipt.attempts.map((attempt) => ({
            key: attempt.seq,
            children: (
              <>
                <Space wrap>
                  <strong>第 {attempt.seq} 次提交</strong>
                  <span>{attempt.provider_code}</span>
                  <Status value={attempt.status} labels={attemptStatus} />
                  {attempt.is_current && <Tag>当前提交</Tag>}
                </Space>
                <Descriptions className="detail-note" size="small" column={{ xs: 1, sm: 2 }} items={[
                  { label: '提交时间', children: dateText(attempt.submitted_at) },
                  { label: '结果时间', children: dateText(attempt.finished_at) },
                  { label: '办理成本', children: money(attempt.cost_fen) },
                  ...(attempt.reject_reason ? [{ label: '驳回原因', children: attempt.reject_reason }] : []),
                ]} />
              </>
            ),
          }))} />
          : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无提交记录" />}
      </Section>
    </>
  )
}

export default function Receipts() {
  const search = useFilters<ReceiptFilters>()
  const query = useCursorList('receipts', (cursor, signal) => adminApi.receipts({ ...search.filters, cursor }, signal), search.version)
  const appNo = useMatch('/receipts/:appNo')?.params.appNo
  const navigate = useNavigate()

  return (
    <>
      <PageHeading title="回执" />
      <FilterForm<ReceiptFilters> onFinish={(values) => search.apply({
        ...values, app_no: values.app_no?.trim() || undefined, spec_code: values.spec_code?.trim() || undefined,
      })}>
        <TextFilter label="申请单号" name="app_no" maxLength={64} />
        <IdFilter />
        <TextFilter label="规格编码" name="spec_code" maxLength={64} />
        <Form.Item label="申请状态" name="status">
          <Select className="filter-select" allowClear options={enumOptions(receiptStatus)} />
        </Form.Item>
      </FilterForm>
      <CursorTable<Schema['AdminApplicationOut']> query={query} rowKey="app_no" columns={[
        { title: '申请单号', render: (_, row) => <Link to={`/receipts/${encodeURIComponent(row.app_no)}`}>{row.app_no}</Link> },
        { title: '用户 ID', dataIndex: 'user_id' },
        { title: '规格', dataIndex: 'spec_name' },
        { title: '状态', render: (_, row) => <Status value={row.status} labels={receiptStatus} /> },
        { title: '重提次数', dataIndex: 'resubmit_count', align: 'right' },
        { title: '创建时间', dataIndex: 'created_at', render: dateText },
        { title: '最近更新', dataIndex: 'updated_at', render: dateText },
      ]} />
      {appNo && (
        <Drawer open title="回执详情" width="min(100vw, 780px)" onClose={() => navigate('/receipts', { replace: true })}>
          <ReceiptDetail key={appNo} appNo={appNo} />
        </Drawer>
      )}
    </>
  )
}
