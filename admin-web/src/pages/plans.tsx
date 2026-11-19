import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, Button, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { changedFields, codeRule, IntegerField, useEditorSave } from '../components/editor'
import { DataTable, PageHeading, Problem, Status } from '../components/ui'
import { benefitTypes, dateText, enumOptions, money, planStatus, yuanToFen, type BenefitType } from '../format'
import { usePermission } from '../session'

type Plan = Schema['AdminPlanOut']
type PlanBody = Schema['AdminPlanCreateIn']
type Benefit = { type: string; value: number }
type PlanForm = {
  code: string
  name: string
  yuan: string
  status: Plan['status']
  sort: number
  sale_starts_at?: Dayjs | null
  sale_ends_at?: Dayjs | null
  displayJson: string
  benefits: Benefit[]
}
const benefitOptions = Object.entries(benefitTypes).map(([value, { label, description }]) => ({
  value, label: `${label} · ${description}`,
}))

function displayObject(raw: string): NonNullable<PlanBody['display']> {
  const value: unknown = JSON.parse(raw)
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('展示配置必须为 JSON 对象')
  }
  return value as NonNullable<PlanBody['display']>
}

function planValues(values: PlanForm, price_fen: number): Omit<PlanBody, 'code'> {
  return {
    name: values.name.trim(),
    price_fen,
    status: values.status,
    sort: values.sort,
    sale_starts_at: values.sale_starts_at?.toISOString() ?? null,
    sale_ends_at: values.sale_ends_at?.toISOString() ?? null,
    display: displayObject(values.displayJson),
    benefits: Object.fromEntries(values.benefits.map(({ type, value }) => [type, value])),
  }
}

function PlanEditor({ plan, onClose }: { plan: Plan | null; onClose: () => void }) {
  const [form] = Form.useForm<PlanForm>()
  const editor = useEditorSave('plans', onClose)
  const initial: PlanForm = {
    code: plan?.code ?? '',
    name: plan?.name ?? '',
    yuan: plan ? (plan.price_fen / 100).toFixed(2) : '0.00',
    status: plan?.status ?? 'draft',
    sort: plan?.sort ?? 0,
    sale_starts_at: plan?.sale_starts_at ? dayjs(plan.sale_starts_at) : null,
    sale_ends_at: plan?.sale_ends_at ? dayjs(plan.sale_ends_at) : null,
    displayJson: JSON.stringify(plan?.display ?? {}, null, 2),
    benefits: Object.entries(plan?.benefits ?? {}).map(([type, value]) => ({ type, value })),
  }

  function submit(values: PlanForm) {
    const fen = yuanToFen(values.yuan)
    if (fen === null) return
    const body = planValues(values, fen)
    if (plan) {
      const previous = { ...planValues(initial, plan.price_fen), name: plan.name }
      const patch = changedFields(previous, body)
      if (Object.keys(patch).length) void editor.save(() => adminApi.updatePlan(plan.code, patch))
      else editor.close()
    } else {
      void editor.save(() => adminApi.createPlan({ ...body, code: values.code }))
    }
  }

  return (
    <Modal open title={plan ? '编辑套餐' : '新建套餐'} width={720} okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit}
      confirmLoading={editor.saving} cancelButtonProps={{ disabled: editor.saving }}
      closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<PlanForm> form={form} layout="vertical" initialValues={initial} disabled={editor.saving} onFinish={submit}>
        <div className="form-grid">
          <Form.Item label="套餐编码" name="code" rules={[{ required: true, message: '请输入套餐编码' }, codeRule]}>
            <Input maxLength={64} disabled={!!plan} />
          </Form.Item>
          <Form.Item label="套餐名称" name="name" rules={[{ required: true, whitespace: true, max: 64, message: '请输入 1～64 字的套餐名称' }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item label="价格（元）" name="yuan" rules={[{
            required: true,
            validator: (_, value: string | null) => {
              const amount = yuanToFen(value ?? '')
              return amount !== null && amount <= 100_000_000
                ? Promise.resolve() : Promise.reject(new Error('请输入 0～1000000 元，最多两位小数'))
            },
          }]}>
            <InputNumber stringMode step="0.01" inputMode="decimal" controls={false} />
          </Form.Item>
          <Form.Item label="状态" name="status"><Select options={enumOptions(planStatus)} /></Form.Item>
          <IntegerField label="排序" name="sort" min={-10_000} max={10_000} required />
          <Form.Item label="开售时间" name="sale_starts_at">
            <DatePicker showTime placeholder="不限" />
          </Form.Item>
          <Form.Item label="停售时间" name="sale_ends_at" dependencies={['sale_starts_at']} rules={[({ getFieldValue }) => ({
            validator: (_, end: Dayjs | null) => {
              const start: Dayjs | undefined = getFieldValue('sale_starts_at')
              return !end || !start || end.isAfter(start)
                ? Promise.resolve() : Promise.reject(new Error('停售时间必须晚于开售时间'))
            },
          })]}>
            <DatePicker showTime placeholder="不限" />
          </Form.Item>
        </div>
        <Form.Item label="展示配置" name="displayJson" extra="填写 JSON 对象，卖点、角标等配置会原样返回小程序。" rules={[{
          validator: (_, value: string) => {
            try {
              displayObject(value)
              return Promise.resolve()
            } catch {
              return Promise.reject(new Error('请输入有效的 JSON 对象，如 {}'))
            }
          },
        }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 7 }} spellCheck={false} />
        </Form.Item>
        <strong>权益配置</strong>
        <Form.List name="benefits" rules={[{
          validator: (_, rows: Benefit[]) => {
            const types = rows.map((row) => row?.type).filter(Boolean)
            return new Set(types).size === types.length
              ? Promise.resolve() : Promise.reject(new Error('同一种权益只能添加一次'))
          },
        }]}>
          {(fields, { add, remove }, { errors }) => (
            <div className="list-editor">
              {fields.map((field) => (
                <div className="editor-row" key={field.key}>
                  <Form.Item className="field-grow" name={[field.name, 'type']} rules={[{ required: true, message: '请选择权益类型' }]}>
                    <Select placeholder="权益类型" aria-label="权益类型" options={benefitOptions} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'value']} rules={[
                    { required: true, message: '请输入数值' },
                    { type: 'integer', min: 0, max: 100_000, message: '请输入 0～100000 的整数' },
                  ]}>
                    <InputNumber min={0} max={100_000} placeholder="数值" aria-label="权益数值" />
                  </Form.Item>
                  <Button icon={<DeleteOutlined />} aria-label="删除权益" onClick={() => remove(field.name)} />
                </div>
              ))}
              <Form.ErrorList errors={errors} />
              {fields.length < benefitOptions.length && (
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ value: 0 })}>添加权益</Button>
              )}
            </div>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}

export default function Plans() {
  const canWrite = usePermission('plan:write')
  const confirm = useConfirmChange('plans')
  const [editing, setEditing] = useState<Plan | null>()
  const query = useQuery({ queryKey: ['plans'], queryFn: ({ signal }) => adminApi.plans(signal) })

  return (
    <>
      <PageHeading title="套餐" action={canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新建套餐</Button>} />
      <div className="data-surface">
        {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
        <DataTable<Plan> rowKey="code" dataSource={query.data} loading={query.isPending} columns={[
          { title: '套餐', dataIndex: 'name' },
          { title: '编码', dataIndex: 'code' },
          { title: '价格', dataIndex: 'price_fen', className: 'amount', align: 'right', render: money },
          { title: '状态', render: (_, row) => <Status value={row.status} labels={planStatus} /> },
          { title: '排序', dataIndex: 'sort', align: 'right' },
          { title: '开售时间', dataIndex: 'sale_starts_at', render: dateText },
          { title: '停售时间', dataIndex: 'sale_ends_at', render: dateText },
          {
            title: '权益',
            render: (_, row) => (
              <Space size={[0, 4]} wrap style={{ maxWidth: 260 }}>
                {Object.entries(row.benefits).map(([key, value]) => (
                  <Tag key={key}>{benefitTypes[key as BenefitType]?.label ?? key} {key === 'photo_scope' && (value === 0 || value === 1)
                    ? value === 0 ? '全部照片' : '单张照片'
                    : value}</Tag>
                ))}
              </Space>
            ),
          },
          ...(canWrite ? [{
            title: '操作',
            render: (_: unknown, plan: Plan) => {
              const isOnSale = plan.status === 'on_sale'
              const action = isOnSale ? '下架' : '上架'
              return (
                <Space>
                  <Button size="small" disabled={query.isFetching} onClick={() => setEditing(plan)}>编辑</Button>
                  <Button size="small" danger={isOnSale} disabled={query.isFetching} onClick={() => confirm({
                    title: `${action}套餐`,
                    content: `确认${action}「${plan.name}」？`,
                    okText: `确认${action}`,
                    okType: isOnSale ? 'danger' : 'primary',
                  }, () => adminApi.updatePlan(plan.code, { status: isOnSale ? 'off_sale' : 'on_sale' }), `套餐已${action}`)}>{action}</Button>
                </Space>
              )
            },
          }] : []),
        ]} />
      </div>
      {canWrite && editing !== undefined && <PlanEditor plan={editing} onClose={() => setEditing(undefined)} />}
    </>
  )
}
