import { Alert, Form, Input, InputNumber, Modal, Select, Switch } from 'antd'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { changedFields, IntegerField, useEditorSave } from '../components/editor'
import { yuanToFen } from '../format'

type ProviderSpecBody = Schema['AdminProviderSpecCreateIn']
type ProviderSpecForm = Omit<ProviderSpecBody, 'cost_fen' | 'param_mapping'> & {
  yuan: string
  mappingJson: string
}
type RouteRuleBody = Schema['AdminRouteRuleCreateIn']
type ProviderEditorProps = {
  providerCode: string
  providerOptions: { value: string; label: string }[]
  onClose: () => void
}

const maxCostFen = 2_147_483_647
const specCodeRule = { required: true, whitespace: true, message: '请输入规格编码' }

function parameterMapping(raw: string) {
  const value: unknown = JSON.parse(raw.trim() || '{}')
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('字段映射须为 JSON 对象')
  }
  const entries = Object.entries(value).map(([key, field]): [string, string] => {
    if (typeof field !== 'string') throw new Error('服务商字段名须为字符串')
    return [key, field]
  })
  return Object.fromEntries(entries)
}

export function ProviderSpecEditor({ providerCode, providerOptions, entry, onClose }: ProviderEditorProps & {
  entry: Schema['AdminProviderSpecOut'] | null
}) {
  const [form] = Form.useForm<ProviderSpecForm>()
  const editor = useEditorSave('providers', onClose)
  const initial: ProviderSpecForm = {
    provider_code: providerCode,
    spec_code: entry?.spec_code ?? '',
    provider_item_id: entry?.provider_item_id ?? '',
    yuan: ((entry?.cost_fen ?? 0) / 100).toFixed(2),
    is_enabled: entry?.is_enabled ?? true,
    mappingJson: JSON.stringify(entry?.param_mapping ?? {}, null, 2),
  }

  function submit(values: ProviderSpecForm) {
    const cost_fen = yuanToFen(values.yuan)
    if (cost_fen === null || cost_fen > maxCostFen) return
    const body: ProviderSpecBody = {
      provider_code: values.provider_code,
      spec_code: values.spec_code.trim(),
      provider_item_id: values.provider_item_id,
      cost_fen,
      is_enabled: values.is_enabled,
    }
    if (entry) {
      const patch = changedFields<ProviderSpecBody>({
        provider_code: entry.provider_code,
        spec_code: entry.spec_code,
        provider_item_id: entry.provider_item_id,
        cost_fen: entry.cost_fen,
        is_enabled: entry.is_enabled,
      }, body)
      if (values.mappingJson !== initial.mappingJson) patch.param_mapping = parameterMapping(values.mappingJson)
      if (Object.keys(patch).length) void editor.save(() => adminApi.updateProviderSpec(entry.id, patch))
      else editor.close()
    } else {
      void editor.save(() => adminApi.createProviderSpec({ ...body, param_mapping: parameterMapping(values.mappingJson) }))
    }
  }

  return (
    <Modal open title={entry ? '编辑服务商规格' : '新增服务商规格'} okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit}
      confirmLoading={editor.saving} cancelButtonProps={{ disabled: editor.saving }}
      closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<ProviderSpecForm> form={form} layout="vertical" initialValues={initial} disabled={editor.saving} onFinish={submit}>
        <div className="form-grid">
          <Form.Item label="服务商" name="provider_code" rules={[{ required: true, message: '请选择服务商' }]}>
            <Select options={providerOptions} />
          </Form.Item>
          <Form.Item label="规格编码" name="spec_code" rules={[specCodeRule]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item label="服务商规格 ID" name="provider_item_id" rules={[{ required: true, whitespace: true, message: '请输入服务商规格 ID' }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item label="办理成本（元）" name="yuan" rules={[{
            required: true,
            validator: (_, value?: string | null) => {
              const fen = yuanToFen(value ?? '')
              return fen !== null && fen <= maxCostFen
                ? Promise.resolve() : Promise.reject(new Error('请输入 0～21474836.47 元，最多两位小数'))
            },
          }]}>
            <InputNumber stringMode step="0.01" inputMode="decimal" controls={false} />
          </Form.Item>
        </div>
        <Form.Item label="字段映射" name="mappingJson" extra={'填写 JSON 对象，如 {"name":"text_name"}。留空可清空映射。'} rules={[{
          validator: (_, value: string) => {
            if (entry && value === initial.mappingJson) return Promise.resolve()
            try {
              parameterMapping(value)
              return Promise.resolve()
            } catch {
              return Promise.reject(new Error('请输入合法的 JSON 对象，字段值须为字符串'))
            }
          },
        }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 7 }} spellCheck={false} />
        </Form.Item>
        <Form.Item label="启用" name="is_enabled" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  )
}

export function RouteRuleEditor({ providerCode, providerOptions, rule, onClose }: ProviderEditorProps & {
  rule: Schema['AdminRouteRuleOut'] | null
}) {
  const [form] = Form.useForm<RouteRuleBody>()
  const editor = useEditorSave('providers', onClose)
  const { id, ...previous } = rule ?? { id: null, provider_code: providerCode, spec_code: '', region_code: null, priority: 100, is_enabled: true }

  function submit(values: RouteRuleBody) {
    const body = { ...values, spec_code: values.spec_code.trim(), region_code: values.region_code?.trim() || null }
    if (id !== null) {
      const patch = changedFields<RouteRuleBody>(previous, body)
      if (Object.keys(patch).length) void editor.save(() => adminApi.updateRouteRule(id, patch))
      else editor.close()
    } else {
      void editor.save(() => adminApi.createRouteRule(body))
    }
  }

  return (
    <Modal open title={rule ? '编辑路由规则' : '新增路由规则'} okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit}
      confirmLoading={editor.saving} cancelButtonProps={{ disabled: editor.saving }}
      closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<RouteRuleBody> form={form} layout="vertical" initialValues={previous} disabled={editor.saving} onFinish={submit}>
        <div className="form-grid">
          <Form.Item label="服务商" name="provider_code" rules={[{ required: true, message: '请选择服务商' }]}>
            <Select options={providerOptions} />
          </Form.Item>
          <Form.Item label="规格编码" name="spec_code" rules={[specCodeRule]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item label="地区码" name="region_code">
            <Input placeholder="不限地区留空" maxLength={32} />
          </Form.Item>
          <IntegerField name="priority" label="优先级" min={-2_147_483_648} max={2_147_483_647} required />
        </div>
        <Form.Item label="启用" name="is_enabled" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  )
}
