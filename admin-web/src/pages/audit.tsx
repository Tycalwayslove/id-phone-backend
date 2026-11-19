import { AutoComplete, Form, Input, Tag } from 'antd'
import { adminApi, type AuditFilters } from '../api/admin'
import type { Schema } from '../api/client'
import { CursorTable, FilterForm, IdFilter, PageHeading, Section, useCursorList, useFilters } from '../components/ui'
import {
  auditActions, auditTargets, benefitTypes, dateText, enumOptions, labelFor, money, orderStatus,
  planStatus, providerStatus, receiptStatus, refundStatus, specCategory, specStatus, type BenefitType,
} from '../format'

type AuditLog = Schema['AdminAuditLogOut']

const targetStatuses: Record<string, Record<string, string>> = {
  order: orderStatus, plan: planStatus, spec: specStatus, provider: providerStatus, receipt_application: receiptStatus,
}
const fieldLabels: Record<string, string> = {
  status: '状态', refund_status: '退款状态', refunded_fen: '已退金额', price_fen: '价格',
  amount_fen: '金额', out_refund_no: '退款单号', code: '编码', name: '名称', category: '分类',
  sort: '排序', sale_starts_at: '开售时间', sale_ends_at: '停售时间', display: '展示配置', benefits: '权益',
  region_code: '地区码', cert_type: '证件类型', width_px: '宽度（像素）', height_px: '高度（像素）',
  width_mm: '宽度（毫米）', height_mm: '高度（毫米）', dpi: '分辨率', bg_colors: '可选底色',
  file_size_min_kb: '文件大小下限（KB）', file_size_max_kb: '文件大小上限（KB）', beauty_max: '最高美颜档位',
  form_schema: '表单字段', official_valid_days: '官方回执有效天数',
}

function formatSnapshot(data: AuditLog['before'], target: string) {
  if (!data) return '—'
  const formatted = Object.fromEntries(Object.entries(data).map(([key, value]) => {
    const label = labelFor(fieldLabels, key)
    if (key.endsWith('_fen') && typeof value === 'number') return [label, money(value)]
    if (key === 'status' && typeof value === 'string') return [label, labelFor(targetStatuses[target] ?? {}, value)]
    if (key === 'refund_status' && typeof value === 'string') return [label, labelFor(refundStatus, value)]
    if (key === 'category' && typeof value === 'string') return [label, labelFor(specCategory, value)]
    if ((key === 'sale_starts_at' || key === 'sale_ends_at') && typeof value === 'string') return [label, dateText(value)]
    if (key === 'benefits' && value && typeof value === 'object') {
      return [label, Object.fromEntries(Object.entries(value).map(([type, amount]) => [
        benefitTypes[type as BenefitType]?.label ?? type, amount,
      ]))]
    }
    return [label, value]
  }))
  return JSON.stringify(formatted, null, 2)
}

export default function Audit() {
  const search = useFilters<AuditFilters>()
  const query = useCursorList('audit', (cursor, signal) => adminApi.auditLogs({ ...search.filters, cursor }, signal), search.version)

  return (
    <>
      <PageHeading title="审计日志" />
      <FilterForm<AuditFilters> onFinish={(values) => search.apply({
        ...values, action: values.action?.trim() || undefined, target_type: values.target_type?.trim() || undefined,
      })}>
        <IdFilter name="admin_id" label="账号 ID" />
        <Form.Item name="action" label="操作类型">
          <AutoComplete className="filter-select" allowClear options={enumOptions(auditActions)}>
            <Input maxLength={64} />
          </AutoComplete>
        </Form.Item>
        <Form.Item name="target_type" label="对象类型">
          <AutoComplete className="filter-select" allowClear options={enumOptions(auditTargets)}>
            <Input maxLength={64} />
          </AutoComplete>
        </Form.Item>
      </FilterForm>
      <CursorTable<AuditLog> query={query} rowKey="id" expandable={{
        rowExpandable: (row) => !!(row.before || row.after),
        expandedRowRender: (row) => (
          <div className="form-grid">
            <Section title="操作前"><pre className="audit-data">{formatSnapshot(row.before, row.target_type)}</pre></Section>
            <Section title="操作后"><pre className="audit-data">{formatSnapshot(row.after, row.target_type)}</pre></Section>
          </div>
        ),
      }} columns={[
        { title: '日志 ID', dataIndex: 'id' },
        { title: '操作人', render: (_, row) => row.admin_username ? `${row.admin_username}（${row.admin_id}）` : row.admin_id },
        { title: '操作', render: (_, row) => <Tag>{labelFor(auditActions, row.action)}</Tag> },
        { title: '对象类型', render: (_, row) => labelFor(auditTargets, row.target_type) },
        { title: '对象 ID', render: (_, row) => row.target_id ?? '—' },
        { title: '操作时间', dataIndex: 'created_at', render: dateText },
      ]} />
    </>
  )
}
