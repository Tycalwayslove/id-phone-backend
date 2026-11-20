import { DeleteOutlined, DownOutlined, PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { Alert, Button, Checkbox, Dropdown, Form, Input, InputNumber, Modal, Select, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { adminApi, type SpecFilters } from '../api/admin'
import type { Schema } from '../api/client'
import { changedFields, codeRule, IntegerField, useEditorSave } from '../components/editor'
import { useSpecSync } from '../components/spec-sync'
import { CursorTable, FilterForm, PageHeading, Status, TextFilter, useCursorList, useFilters } from '../components/ui'
import { dateText, enumOptions, specCategory, specStatus } from '../format'
import { usePermission } from '../session'

type Spec = Schema['AdminSpecOut']
type SpecBody = Schema['AdminSpecCreateIn']
type FormField = NonNullable<SpecBody['form_schema']>[number]
const hexColor = /^#[0-9A-Fa-f]{6}$/

function specFields(values: SpecBody): Omit<SpecBody, 'code' | 'parent_code'> {
  return {
    name: values.name,
    category: values.category,
    cert_type: values.cert_type,
    region_code: values.region_code ?? null,
    width_px: values.width_px,
    height_px: values.height_px,
    width_mm: values.width_mm ?? null,
    height_mm: values.height_mm ?? null,
    dpi: values.dpi,
    bg_colors: values.bg_colors,
    file_size_min_kb: values.file_size_min_kb ?? null,
    file_size_max_kb: values.file_size_max_kb ?? null,
    beauty_max: values.beauty_max,
    form_schema: values.form_schema?.map((field) => ({ ...field, required: field.required ?? true })) ?? [],
    official_valid_days: values.official_valid_days ?? null,
    status: values.status,
    sort: values.sort,
  }
}

function SpecEditor({ spec, onClose }: { spec: Spec | null; onClose: () => void }) {
  const [form] = Form.useForm<SpecBody>()
  const editor = useEditorSave('specs', onClose)
  const initial = spec ? { ...specFields(spec), code: spec.code, parent_code: spec.parent_code } : {
    category: 'normal', status: 'active', dpi: 300, beauty_max: 0, sort: 0,
    bg_colors: ['#FFFFFF'], form_schema: [],
  }

  function submit(values: SpecBody) {
    const current = specFields(values)
    const body = {
      ...current,
      name: current.name.trim(),
      cert_type: current.cert_type.trim(),
      region_code: current.region_code?.trim() || null,
      form_schema: current.form_schema?.map((field) => ({
        ...field, key: field.key.trim(), label: field.label.trim(),
      })),
    }
    if (spec) {
      const patch = changedFields(specFields(spec), body)
      if (Object.keys(patch).length) void editor.save(() => adminApi.updateSpec(spec.code, patch))
      else editor.close()
    } else {
      void editor.save(() => adminApi.createSpec({
        ...body,
        code: values.code,
        parent_code: values.parent_code?.trim() || null,
      }))
    }
  }

  return (
    <Modal open title={spec ? '编辑规格' : '新建规格'} width={820} okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit}
      confirmLoading={editor.saving} cancelButtonProps={{ disabled: editor.saving }}
      closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<SpecBody> form={form} layout="vertical" initialValues={initial} disabled={editor.saving} onFinish={submit}>
        <div className="form-grid">
          <Form.Item label="规格编码" name="code" rules={[{ required: true, message: '请输入规格编码' }, codeRule]}>
            <Input maxLength={64} disabled={!!spec} />
          </Form.Item>
          <Form.Item label="规格名称" name="name" rules={[{ required: true, whitespace: true, max: 64, message: '请输入 1～64 字的规格名称' }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item label="父规格编码" name="parent_code"><Input placeholder="顶级规格留空" maxLength={64} disabled={!!spec} /></Form.Item>
          <Form.Item label="分类" name="category"><Select options={enumOptions(specCategory)} /></Form.Item>
          <Form.Item label="证件类型标识" name="cert_type" rules={[{ required: true, whitespace: true, max: 32, message: '请输入 1～32 字的证件类型标识' }]}>
            <Input maxLength={32} placeholder="例如 idcard" />
          </Form.Item>
          <Form.Item label="地区码" name="region_code"><Input placeholder="不限地区留空" maxLength={12} /></Form.Item>
          <IntegerField name="width_px" label="成品宽度（像素）" min={1} max={10_000} required />
          <IntegerField name="height_px" label="成品高度（像素）" min={1} max={10_000} required />
          <IntegerField name="width_mm" label="成品宽度（毫米）" min={1} max={1_000} />
          <IntegerField name="height_mm" label="成品高度（毫米）" min={1} max={1_000} />
          <IntegerField name="dpi" label="分辨率（dpi）" min={1} max={1_200} required />
          <IntegerField name="beauty_max" label="最高美颜档位" min={0} max={5} required />
          <IntegerField name="file_size_min_kb" label="文件大小下限（KB）" min={0} />
          <Form.Item label="文件大小上限（KB）" name="file_size_max_kb" dependencies={['file_size_min_kb']} rules={[
            { type: 'integer', min: 1, message: '请输入正整数' },
            ({ getFieldValue }) => ({
              validator: (_, max: number | null) => {
                const min: number | null = getFieldValue('file_size_min_kb')
                return max == null || min == null || max >= min
                  ? Promise.resolve() : Promise.reject(new Error('文件大小上限不得小于下限'))
              },
            }),
          ]}>
            <InputNumber min={1} />
          </Form.Item>
          <IntegerField name="official_valid_days" label="官方回执有效天数" min={1} />
          <Form.Item label="状态" name="status"><Select options={enumOptions(specStatus)} /></Form.Item>
          <IntegerField name="sort" label="排序" min={-10_000} max={10_000} required />
        </div>

        <strong>可选底色</strong>
        <Form.List name="bg_colors" rules={[{
          validator: (_, colors: string[]) => colors?.length >= 1 && colors.length <= 10
            ? Promise.resolve() : Promise.reject(new Error('请添加 1～10 种底色')),
        }]}>
          {(fields, { add, remove }, { errors }) => (
            <div className="list-editor">
              {fields.map((field, index) => (
                <div key={field.key} className="editor-row">
                  <Form.Item className="field-grow" name={field.name} rules={[
                    { required: true, pattern: hexColor, message: '请输入十六进制颜色，如 #FFFFFF' },
                  ]}>
                    <Input maxLength={7} placeholder="#FFFFFF" aria-label={index === 0 ? '默认底色' : `底色 ${index + 1}`} />
                  </Form.Item>
                  {index === 0 && <span>默认底色</span>}
                  <Button icon={<DeleteOutlined />} disabled={editor.saving || fields.length === 1} aria-label="删除底色" onClick={() => remove(field.name)} />
                </div>
              ))}
              <Form.ErrorList errors={errors} />
              {fields.length < 10 && <Button type="dashed" icon={<PlusOutlined />} onClick={() => add()}>添加底色</Button>}
            </div>
          )}
        </Form.List>

        <strong>回执表单字段</strong>
        <Form.List name="form_schema" rules={[{
          validator: (_, rows: FormField[]) => {
            const keys = rows.map((row) => row?.key?.trim()).filter(Boolean)
            return new Set(keys).size === keys.length
              ? Promise.resolve() : Promise.reject(new Error('字段标识不能重复'))
          },
        }]}>
          {(fields, { add, remove }, { errors }) => (
            <div className="list-editor">
              {fields.map((field) => (
                <div className="editor-row" key={field.key}>
                  <Form.Item className="field-grow" name={[field.name, 'key']} rules={[{ required: true, whitespace: true, message: '请输入字段标识' }]}>
                    <Input placeholder="字段标识，如 name" aria-label="字段标识" />
                  </Form.Item>
                  <Form.Item className="field-grow" name={[field.name, 'label']} rules={[{ required: true, whitespace: true, message: '请输入字段名称' }]}>
                    <Input placeholder="字段名称，如 姓名" aria-label="字段名称" />
                  </Form.Item>
                  <Form.Item name={[field.name, 'required']} valuePropName="checked"><Checkbox>必填</Checkbox></Form.Item>
                  <Button icon={<DeleteOutlined />} aria-label="删除表单字段" onClick={() => remove(field.name)} />
                </div>
              ))}
              <Form.ErrorList errors={errors} />
              {fields.length < 20 && <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ required: true })}>添加字段</Button>}
            </div>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}

type Filters = Omit<SpecFilters, 'cursor' | 'limit'>

/** 从服务商同步规格目录（仅 owner 有 provider:write）。 */
function SyncSpecsButton() {
  const { sync, syncing, reportModal } = useSpecSync()
  const providers = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => adminApi.providers(signal) })
  const items = (providers.data ?? []).map((provider) => ({
    key: provider.code,
    label: `${provider.name}（${provider.code}）`,
    onClick: () => sync(provider),
  }))
  return (
    <>
      <Dropdown disabled={syncing !== undefined || !items.length} menu={{ items }} trigger={['click']}>
        <Button icon={<SyncOutlined />} loading={syncing !== undefined || providers.isPending}>
          同步规格 <DownOutlined />
        </Button>
      </Dropdown>
      {reportModal}
    </>
  )
}

export default function Specs() {
  const canWrite = usePermission('spec:write')
  const canSync = usePermission('provider:write')
  const [editing, setEditing] = useState<Spec | null>()
  const search = useFilters<Filters>()
  const query = useCursorList('specs', (cursor, signal) => adminApi.specs({ ...search.filters, cursor }, signal), search.version)

  return (
    <>
      <PageHeading title="规格" action={(canSync || canWrite) && (
        <Space>
          {canSync && <SyncSpecsButton />}
          {canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新建规格</Button>}
        </Space>
      )} />
      <FilterForm<Filters> onFinish={(values) => search.apply({ ...values, keyword: values.keyword?.trim() || undefined })}>
        <TextFilter name="keyword" label="名称或编码" maxLength={64} />
        <Form.Item label="状态" name="status">
          <Select className="filter-select" allowClear options={enumOptions(specStatus)} placeholder="全部" />
        </Form.Item>
        <Form.Item label="分类" name="category">
          <Select className="filter-select" allowClear options={enumOptions(specCategory)} placeholder="全部" />
        </Form.Item>
      </FilterForm>
      <CursorTable<Spec> query={query} rowKey="code" columns={[
        { title: '规格', dataIndex: 'name' },
        { title: '编码', dataIndex: 'code' },
        { title: '分类', render: (_, row) => specCategory[row.category] },
        { title: '地区码', render: (_, row) => row.region_code ?? '不限' },
        { title: '成品尺寸', render: (_, row) => `${row.width_px} × ${row.height_px} 像素` },
        { title: '可选底色', render: (_, row) => (
          <Space size={4}>
            {row.bg_colors.map((color, index) => (
              <span key={`${color}-${index}`} className="color-swatch" role="img"
                title={`${color}${index === 0 ? '（默认）' : ''}`}
                aria-label={`${color}${index === 0 ? '，默认底色' : ''}`}
                style={{ backgroundColor: hexColor.test(color) ? color : 'transparent' }}
              />
            ))}
          </Space>
        ) },
        { title: '状态', render: (_, row) => <Status value={row.status} labels={specStatus} /> },
        { title: '最近修改', dataIndex: 'updated_at', render: dateText },
        ...(canWrite ? [{
          title: '操作',
          render: (_: unknown, spec: Spec) => <Button size="small" disabled={query.isFetching} onClick={() => setEditing(spec)}>编辑</Button>,
        }] : []),
      ]} />
      {canWrite && editing !== undefined && <SpecEditor spec={editing} onClose={() => setEditing(undefined)} />}
    </>
  )
}
