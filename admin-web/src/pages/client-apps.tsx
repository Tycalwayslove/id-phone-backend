import { Alert, Button, Form, Input, Modal, Select } from 'antd'
import { useState } from 'react'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { changedFields, useEditorSave } from '../components/editor'
import { CursorTable, PageHeading, Status, useCursorList } from '../components/ui'
import { clientAppPlatforms, clientAppStatus, enumOptions } from '../format'

type ClientApp = Schema['AdminClientAppOut']
type AppForm = Pick<ClientApp, 'name' | 'status'>

function AppEditor({ app, onClose }: { app: ClientApp; onClose: () => void }) {
  const [form] = Form.useForm<AppForm>()
  const editor = useEditorSave('client-apps', onClose)
  const initial = { name: app.name, status: app.status }

  function submit(values: AppForm) {
    const patch = changedFields(initial, { name: values.name.trim(), status: values.status })
    if (Object.keys(patch).length) void editor.save(() => adminApi.updateClientApp(app.id, patch))
    else editor.close()
  }

  return (
    <Modal open title="编辑来源应用" okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit} confirmLoading={editor.saving}
      cancelButtonProps={{ disabled: editor.saving }} closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<AppForm> form={form} layout="vertical" initialValues={initial} onFinish={submit} disabled={editor.saving}>
        <Form.Item name="name" label="应用名称" rules={[{ required: true, whitespace: true, max: 128, message: '请输入 1～128 字的应用名称' }]}>
          <Input maxLength={128} />
        </Form.Item>
        <Form.Item name="status" label="运营状态" extra="应用停用后仍保留注册归因，用户登录按原规则处理。">
          <Select options={enumOptions(clientAppStatus)} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default function ClientApps() {
  const query = useCursorList('client-apps', (cursor, signal) => adminApi.clientApps({ cursor }, signal))
  const [editing, setEditing] = useState<ClientApp>()

  return (
    <>
      <PageHeading title="应用" />
      <CursorTable<ClientApp> query={query} rowKey="id" columns={[
        { title: '应用名称', dataIndex: 'name' },
        { title: '平台', render: (_, app) => clientAppPlatforms[app.platform] },
        { title: 'AppID', dataIndex: 'app_id' },
        { title: '注册用户数', dataIndex: 'user_count', align: 'right' },
        { title: '运营状态', render: (_, app) => <Status value={app.status} labels={clientAppStatus} /> },
        { title: '操作', render: (_, app) => <Button type="link" onClick={() => setEditing(app)}>编辑</Button> },
      ]} />
      {editing && <AppEditor app={editing} onClose={() => setEditing(undefined)} />}
    </>
  )
}
