import { Alert, App, Button, DatePicker, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Tag } from 'antd'
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Dayjs } from 'dayjs'
import { useRef, useState } from 'react'
import { Link, useMatch, useNavigate } from 'react-router-dom'
import { adminApi, type OrderFilters } from '../api/admin'
import { errorText, type Schema } from '../api/client'
import { CursorTable, DataTable, FilterForm, IdFilter, Loading, PageHeading, Problem, Section, Status, TextFilter, useCursorList, useFilters } from '../components/ui'
import { dateText, enumOptions, labelFor, money, orderItem, orderStatus, paymentChannels, paymentStatus, refundStatus, yuanToFen } from '../format'
import { usePermission } from '../session'

type Order = Schema['AdminOrderDetail']
type Refund = Schema['AdminRefundIn']
type RefundForm = { yuan: string | null; reason: string }
type Filters = Omit<OrderFilters, 'created_from' | 'created_to'> & { created?: [Dayjs | null, Dayjs | null] }

function RefundDialog({ order, limit, onClose }: { order: Order; limit: number; onClose: () => void }) {
  const [form] = Form.useForm<RefundForm>()
  const { message } = App.useApp()
  const cache = useQueryClient()
  const [confirmation, setConfirmation] = useState<Refund>()
  const inFlight = useRef(false)
  // 每次打开退款弹窗生成一次，重试同一次退款时服务端按它去重
  const [requestId] = useState(() => crypto.randomUUID())
  const mutation = useMutation({
    mutationKey: ['refund', order.order_no],
    mutationFn: (body: Refund) => adminApi.refund(order.order_no, body),
    onSettled: () => Promise.all([
      cache.invalidateQueries({ queryKey: ['orders'] }),
      cache.invalidateQueries({ queryKey: ['audit'] }),
    ]),
  })
  const sending = mutation.isPending

  async function confirm() {
    if (!confirmation || inFlight.current) return
    if (confirmation.amount_fen > limit) {
      setConfirmation(undefined)
      form.setFields([{ name: 'yuan', errors: ['当前可退余额已变化，请重新核对金额'] }])
      return
    }
    inFlight.current = true
    try {
      const refund = await mutation.mutateAsync(confirmation)
      if (refund.status === 'failed') void message.error('退款失败，请查看退款记录。')
      else if (refund.status === 'pending') void message.info('已发起退款，等待支付渠道处理。')
      else void message.success('退款成功')
    } catch (error) {
      void message.error(`${errorText(error)} 请核对退款记录后再操作。`)
    } finally {
      onClose()
    }
  }

  return (
    <Modal
      open title={confirmation ? '确认退款' : '发起退款'}
      okText={confirmation ? '确认原路退款' : '核对退款信息'}
      okButtonProps={{ danger: !!confirmation }}
      cancelText={confirmation ? '返回修改' : '取消'}
      confirmLoading={sending}
      cancelButtonProps={{ disabled: sending }}
      closable={!sending} maskClosable={false} keyboard={!sending}
      onCancel={() => {
        if (inFlight.current) return
        if (confirmation) setConfirmation(undefined)
        else onClose()
      }}
      onOk={() => { if (confirmation) void confirm(); else form.submit() }}
    >
      {confirmation && (
        <Descriptions bordered size="small" column={1} items={[
          { label: '订单号', children: order.order_no },
          { label: '退款金额', children: money(confirmation.amount_fen) },
          { label: '退款原因', children: confirmation.reason },
        ]} />
      )}
      <Form<RefundForm>
        form={form} layout="vertical" hidden={!!confirmation}
        onFinish={(values) => {
          const amount = yuanToFen(values.yuan ?? '')
          if (amount !== null) setConfirmation({ request_id: requestId, amount_fen: amount, reason: values.reason.trim() })
        }}
      >
        <Alert className="detail-note" type="info" message={`当前可退 ${money(limit)}`} />
        <Form.Item name="yuan" label="退款金额（元）" rules={[{
          required: true,
          validator: (_, value: string | null) => {
            const amount = yuanToFen(value ?? '')
            return amount === null || amount < 1 || amount > limit
              ? Promise.reject(new Error(`请输入大于 0 且不超过 ${money(limit)} 的金额，最多两位小数`))
              : Promise.resolve()
          },
        }]}>
          <InputNumber stringMode step="0.01" controls={false} inputMode="decimal" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="reason" label="退款原因" extra="退款原因会写入审计日志，请勿填写手机号或身份证号。" rules={[
          { required: true, whitespace: true, max: 200, message: '请输入 1～200 字的退款原因' },
        ]}>
          <Input.TextArea rows={3} maxLength={200} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function OrderDetail({ orderNo }: { orderNo: string }) {
  const [refundOpen, setRefundOpen] = useState(false)
  const canRefund = usePermission('refund:create')
  const canReadUsers = usePermission('user:read')
  const refundInProgress = useIsMutating({ mutationKey: ['refund', orderNo] }) > 0
  const query = useQuery({
    queryKey: ['orders', 'detail', orderNo],
    queryFn: ({ signal }) => adminApi.order(orderNo, signal),
  })
  if (query.isError) return <Problem error={query.error} retry={() => { void query.refetch() }} />
  if (!query.data) return <Loading />
  const order = query.data
  const pendingRefunds = order.refunds.reduce((sum, refund) => sum + (refund.status === 'pending' ? refund.amount_fen : 0), 0)
  const limit = Math.min(100_000_000, order.paid_fen - order.refunded_fen - pendingRefunds)

  return (
    <>
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
        { label: '订单号', children: order.order_no },
        { label: '状态', children: <Status value={order.status} labels={orderStatus} /> },
        { label: '用户 ID', children: canReadUsers ? <Link to={`/users/${order.user_id}`}>{order.user_id}</Link> : order.user_id },
        { label: '应付金额', children: money(order.total_fen) },
        { label: '实付金额', children: money(order.paid_fen) },
        { label: '已退金额', children: money(order.refunded_fen) },
        { label: '下单时间', children: dateText(order.created_at) },
        { label: '支付时间', children: dateText(order.paid_at) },
      ]} />
      {canRefund && limit > 0 && (order.status === 'paid' || order.status === 'part_refunded') && (
        <Button className="detail-note" danger disabled={query.isFetching || refundInProgress} onClick={() => setRefundOpen(true)}>发起退款</Button>
      )}
      <Section title="订单项">
        <DataTable<Schema['OrderItemOut']> rowKey={(_, index) => String(index)} dataSource={order.items} columns={[
          { title: '类型', render: (_, row) => orderItem[row.item_type] },
          { title: '套餐', render: (_, row) => row.plan_name ?? row.plan_code ?? '—' },
          { title: '照片 ID', render: (_, row) => row.photo_id ?? '—' },
          { title: '金额', dataIndex: 'amount_fen', align: 'right', className: 'amount', render: money },
        ]} />
      </Section>
      <Section title="支付记录">
        <DataTable<Schema['AdminPaymentOut']> rowKey="out_trade_no" dataSource={order.payments} columns={[
          { title: '商户支付单号', dataIndex: 'out_trade_no' },
          { title: '渠道交易号', render: (_, row) => row.transaction_id ?? '—' },
          { title: '渠道', render: (_, row) => labelFor(paymentChannels, row.channel) },
          { title: '金额', dataIndex: 'amount_fen', align: 'right', className: 'amount', render: money },
          { title: '状态', render: (_, row) => <Status value={row.status} labels={paymentStatus} /> },
          { title: '支付时间', dataIndex: 'paid_at', render: dateText },
        ]} />
      </Section>
      <Section title="退款记录">
        <DataTable<Schema['AdminRefundOut']> rowKey="out_refund_no" dataSource={order.refunds} columns={[
          { title: '退款单号', dataIndex: 'out_refund_no' },
          { title: '金额', dataIndex: 'amount_fen', align: 'right', className: 'amount', render: money },
          { title: '状态', render: (_, row) => <Status value={row.status} labels={refundStatus} /> },
          { title: '原因', dataIndex: 'reason', width: 180 },
          { title: '操作人', render: (_, row) => row.operator === 'system' ? <Tag>系统</Tag> : row.operator },
          { title: '发起时间', dataIndex: 'created_at', render: dateText },
          { title: '完成时间', dataIndex: 'finished_at', render: dateText },
        ]} />
      </Section>
      {refundOpen && <RefundDialog order={order} limit={limit} onClose={() => setRefundOpen(false)} />}
    </>
  )
}

export default function Orders() {
  const search = useFilters<OrderFilters>()
  const query = useCursorList('orders', (cursor, signal) => adminApi.orders({ ...search.filters, cursor }, signal), search.version)
  const orderNo = useMatch('/orders/:orderNo')?.params.orderNo
  const navigate = useNavigate()

  return (
    <>
      <PageHeading title="订单" />
      <FilterForm<Filters> onFinish={({ created, ...values }) => search.apply({
        ...values,
        order_no: values.order_no?.trim() || undefined,
        created_from: created?.[0]?.toISOString(),
        created_to: created?.[1]?.toISOString(),
      })}>
        <TextFilter label="订单号" name="order_no" maxLength={64} />
        <IdFilter />
        <Form.Item label="订单状态" name="status">
          <Select className="filter-select" allowClear options={enumOptions(orderStatus)} />
        </Form.Item>
        <Form.Item label="下单时间（含起点）" name="created" rules={[{
          validator: (_, value: Filters['created']) => !value?.[0] || !value[1] || value[1].isAfter(value[0])
            ? Promise.resolve() : Promise.reject(new Error('终点须晚于起点')),
        }]}>
          <DatePicker.RangePicker showTime allowEmpty={[true, true]} />
        </Form.Item>
      </FilterForm>
      <CursorTable<Schema['AdminOrderOut']> query={query} rowKey="order_no" columns={[
        { title: '订单号', render: (_, row) => <Link to={`/orders/${encodeURIComponent(row.order_no)}`}>{row.order_no}</Link> },
        { title: '用户 ID', dataIndex: 'user_id' },
        { title: '状态', render: (_, row) => <Status value={row.status} labels={orderStatus} /> },
        { title: '应付', dataIndex: 'total_fen', align: 'right', className: 'amount', render: money },
        { title: '实付', dataIndex: 'paid_fen', align: 'right', className: 'amount', render: money },
        { title: '已退', dataIndex: 'refunded_fen', align: 'right', className: 'amount', render: money },
        { title: '下单时间', dataIndex: 'created_at', render: dateText },
        { title: '支付时间', dataIndex: 'paid_at', render: dateText },
      ]} />
      {orderNo && (
        <Drawer open title="订单详情" width="min(100vw, 960px)" onClose={() => navigate('/orders', { replace: true })}>
          <OrderDetail key={orderNo} orderNo={orderNo} />
        </Drawer>
      )}
    </>
  )
}
