import { Alert, Button, Descriptions, Drawer, Empty, Form, Image, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useLocation, useMatch, useNavigate } from 'react-router-dom'
import { adminApi, type ReceiptFilters } from '../api/admin'
import type { Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { useEditorSave } from '../components/editor'
import { PhotoView } from '../components/photo-gallery'
import { PagedTable, FilterForm, IdFilter, Loading, PageHeading, Problem, Section, Status, TextFilter, usePagedList } from '../components/ui'
import { attemptStatus, dateText, enumOptions, labelFor, money, qualityLevels, receiptStatus } from '../format'
import { usePermission } from '../session'

const formLabels = { name: '姓名', id_no: '身份证号', id_card: '身份证号', id_number: '身份证号', phone: '手机号', mobile: '手机号' }

type ReviewInput = Schema['AdminManualReviewIn']
type ReceiptFilterForm = Omit<ReceiptFilters, 'manual_review'> & { manual_review?: 'true' | 'false' }
const reviewResults = { completed: '已出回执（仅登记结论）', rejected: '已驳回', failed: '办理失败' } satisfies Record<ReviewInput['result'], string>

function ManualReviewDialog({ appNo, onClose }: { appNo: string; onClose: () => void }) {
  const [form] = Form.useForm<ReviewInput>()
  const { saving, error, save, close } = useEditorSave('receipts', onClose)
  return (
    <Modal open title="标记已核对" okText="提交核对结论" cancelText="取消"
      onOk={() => form.submit()} onCancel={close} confirmLoading={saving}
      cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={false} keyboard={!saving}>
      {error && <Alert className="detail-note" type="error" showIcon message={error} />}
      <Form<ReviewInput> form={form} layout="vertical" disabled={saving}
        onFinish={(values) => { void save(() => adminApi.resolveReceiptReview(appNo, { ...values, remark: values.remark.trim() })) }}>
        <Form.Item label="核对结论" name="result" rules={[{ required: true, message: '请选择核对结论' }]}>
          <Select options={enumOptions(reviewResults)} />
        </Form.Item>
        <Form.Item label="核对备注" name="remark" extra="备注仅用于后台审计。请勿填写手机号、身份证号、令牌或密钥。"
          rules={[{ required: true, whitespace: true, max: 200, message: '请输入 1～200 字的核对备注' }]}>
          <Input.TextArea rows={3} maxLength={200} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function ReceiptImage({ label, url, reason, refresh }: {
  label: string
  url?: string | null
  reason?: string | null
  refresh: () => void
}) {
  const [failedUrl, setFailedUrl] = useState<string>()
  return (
    <div className="receipt-image">
      {url && url !== failedUrl
        ? <Image src={url} alt={label} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailedUrl(url)} />
        : <div className="receipt-image-placeholder">
          {url ? <>
            <span>图片加载失败</span>
            <Button type="link" size="small" onClick={() => { setFailedUrl(undefined); refresh() }}>刷新图片</Button>
          </> : <span>{reason ?? '暂无图片'}</span>}
        </div>}
    </div>
  )
}

function ReceiptDetail({ appNo }: { appNo: string }) {
  const [reviewOpen, setReviewOpen] = useState(false)
  const [photoOpen, setPhotoOpen] = useState(false)
  const canOperate = usePermission('application:operate')
  const canReadUsers = usePermission('user:read')
  const canReadPhotos = usePermission('photo:read')
  const confirm = useConfirmChange('receipts')
  const query = useQuery({
    queryKey: ['receipts', 'detail', appNo],
    queryFn: ({ signal }) => adminApi.receipt(appNo, signal),
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  if (query.isError) return <Problem error={query.error} retry={() => { void query.refetch() }} />
  if (!query.data) return <Loading />
  const receipt = query.data
  const fields = Object.entries(receipt.form_masked)
  const photo = canReadPhotos ? receipt.photo : null
  const finalAttempt = receipt.attempts.find((attempt) => attempt.is_current) ?? receipt.attempts.at(-1)
  const finalRender = canReadPhotos ? finalAttempt?.render : null
  const photoPermissionMessage = canReadPhotos ? undefined : '需要照片查看权限'
  const refresh = () => { void query.refetch() }

  return (
    <>
      <div className="receipt-images" aria-label="回执相关图片">
        <figure>
          <figcaption>用户照片</figcaption>
          <ReceiptImage label="用户照片" url={photo?.thumbnail_url}
            reason={photoPermissionMessage ?? photo?.missing_reason} refresh={refresh} />
          {photo && <Space wrap size={[8, 4]}>
            <Button type="link" size="small" onClick={() => setPhotoOpen(true)}>照片详情 #{photo.id}</Button>
            {photo.quality && <Status value={photo.quality.level} labels={qualityLevels} />}
          </Space>}
        </figure>
        <figure>
          <figcaption>最终提交的证件照</figcaption>
          <ReceiptImage label="最终提交的证件照" url={finalRender?.url}
            reason={photoPermissionMessage ?? finalRender?.missing_reason ?? '暂无提交照片'} refresh={refresh} />
          {finalRender && <span className="receipt-image-caption">
            {finalRender.spec_name} / {finalRender.bg_color} / 美颜 {finalRender.beauty_level} / {finalRender.watermarked ? '有水印' : '无水印'}
          </span>}
        </figure>
        <figure>
          <figcaption>官方回执图</figcaption>
          <ReceiptImage label="官方回执图" url={canReadPhotos ? receipt.receipt_image_url : null}
            reason={photoPermissionMessage ?? receipt.receipt_image_missing_reason} refresh={refresh} />
        </figure>
      </div>
      {photoOpen && photo && <PhotoView key={photo.id} id={photo.id} onClose={() => setPhotoOpen(false)} />}
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
        { label: '申请单号', children: receipt.app_no },
        { label: '状态', children: <Space wrap>
          <Status value={receipt.status} labels={receiptStatus} />
          {receipt.manual_review_required && <Tag color="warning">需人工核对</Tag>}
        </Space> },
        { label: '用户 ID', children: canReadUsers ? <Link to={`/users/${receipt.user_id}`}>{receipt.user_id}</Link> : receipt.user_id },
        { label: '规格', children: `${receipt.spec_name}（${receipt.spec_code}）` },
        { label: '地区码', children: receipt.region_code ?? '不限' },
        { label: '照片 ID', children: receipt.photo_id },
        { label: '权益 ID', children: receipt.entitlement_id },
        { label: '重提次数', children: receipt.resubmit_count },
        { label: '回执图像号', children: receipt.image_code ? <Typography.Text copyable>{receipt.image_code}</Typography.Text> : '—' },
        { label: '创建时间', children: dateText(receipt.created_at) },
        { label: '最近更新', children: dateText(receipt.updated_at) },
        { label: '驳回时间', children: dateText(receipt.rejected_at) },
        { label: '出回执时间', children: dateText(receipt.completed_at) },
        { label: '官方有效期截止', children: dateText(receipt.official_expire_at) },
      ]} />
      {receipt.reject_reason && <Alert className="detail-note" type="warning" showIcon message="当前驳回原因" description={receipt.reject_reason} />}
      {canOperate && receipt.manual_review_required && (
        <Button className="detail-note" type="primary" disabled={query.isFetching} onClick={() => setReviewOpen(true)}>标记已核对</Button>
      )}
      {reviewOpen && canOperate && <ManualReviewDialog appNo={appNo} onClose={() => setReviewOpen(false)} />}
      {canOperate && (receipt.status === 'pending' || receipt.status === 'rejected') && (
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
        <Table<Schema['AdminAttemptOut']> className="receipt-attempts" size="small" rowKey="seq"
          dataSource={receipt.attempts} pagination={false} scroll={{ x: 620 }} locale={{ emptyText: '暂无提交记录' }}
          columns={[
            { title: '证件照', width: 88, render: (_, attempt) => <ReceiptImage
              label={`第 ${attempt.seq} 次提交的证件照`} url={canReadPhotos ? attempt.render?.url : null}
              reason={photoPermissionMessage ?? attempt.render?.missing_reason ?? '暂无提交照片'} refresh={refresh}
            /> },
            { title: '提交记录', width: 160, render: (_, attempt) => <Space direction="vertical" size={3}>
              <strong>第 {attempt.seq} 次提交</strong>
              <span>{attempt.provider_code}</span>
              <Space wrap size={[0, 4]}>
                <Status value={attempt.status} labels={attemptStatus} />
                {attempt.is_current && <Tag>当前提交</Tag>}
              </Space>
            </Space> },
            { title: '提交／结果时间', width: 170, render: (_, attempt) => <>
              <div>{dateText(attempt.submitted_at)}</div>
              <div>{dateText(attempt.finished_at)}</div>
            </> },
            { title: '成本', dataIndex: 'cost_fen', width: 70, render: money },
            { title: '驳回原因', dataIndex: 'reject_reason', render: (reason) => reason ?? '—' },
          ]} />
      </Section>
    </>
  )
}

export default function Receipts() {
  const query = usePagedList('receipts', adminApi.receipts, {} satisfies ReceiptFilters)
  const appNo = useMatch('/receipts/:appNo')?.params.appNo
  const navigate = useNavigate()
  const { search } = useLocation()

  return (
    <>
      <PageHeading title="回执" />
      <FilterForm<ReceiptFilterForm> onFinish={(values) => query.apply({
        ...values, app_no: values.app_no?.trim() || undefined, spec_code: values.spec_code?.trim() || undefined,
        manual_review: values.manual_review == null ? undefined : values.manual_review === 'true',
      })}>
        <TextFilter label="申请单号" name="app_no" maxLength={64} />
        <IdFilter />
        <TextFilter label="规格编码" name="spec_code" maxLength={64} />
        <Form.Item label="申请状态" name="status">
          <Select className="filter-select" allowClear options={enumOptions(receiptStatus)} />
        </Form.Item>
        <Form.Item label="人工核对" name="manual_review">
          <Select className="filter-select" allowClear options={[
            { value: 'true', label: '需人工核对' },
            { value: 'false', label: '无需人工核对' },
          ]} />
        </Form.Item>
      </FilterForm>
      <PagedTable<Schema['AdminApplicationOut']> query={query} rowKey="app_no" columns={[
        { title: '申请单号', render: (_, row) => <Link to={{ pathname: `/receipts/${encodeURIComponent(row.app_no)}`, search }}>{row.app_no}</Link> },
        { title: '用户 ID', dataIndex: 'user_id' },
        { title: '规格', dataIndex: 'spec_name' },
        { title: '状态', render: (_, row) => <Space wrap>
          <Status value={row.status} labels={receiptStatus} />
          {row.manual_review_required && <Tag color="warning">需人工核对</Tag>}
        </Space> },
        { title: '重提次数', dataIndex: 'resubmit_count', align: 'right' },
        { title: '创建时间', dataIndex: 'created_at', render: dateText },
        { title: '最近更新', dataIndex: 'updated_at', render: dateText },
      ]} />
      {appNo && (
        <Drawer open title="回执详情" width="min(100vw, 780px)" onClose={() => navigate({ pathname: '/receipts', search }, { replace: true })}>
          <ReceiptDetail key={appNo} appNo={appNo} />
        </Drawer>
      )}
    </>
  )
}
