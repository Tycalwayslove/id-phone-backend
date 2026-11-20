import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { adminApi } from '../api/admin'
import { errorText, type Schema } from '../api/client'
import { useConfirmChange } from '../components/confirm'
import { useEditorSave } from '../components/editor'
import { CursorTable, PageHeading, Status, useCursorList } from '../components/ui'
import { adminAccountStatus, adminRole, dateText, enumOptions } from '../format'
import { usePermission, useSession } from '../session'

type Account = Schema['AdminAccountOut']
type AccountForm = Schema['AdminAccountCreateIn']
const resource = 'admin-accounts'
const roleOptions = enumOptions(adminRole)

function AccountEditor({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const [form] = Form.useForm<AccountForm>()
  const editor = useEditorSave(resource, onClose)

  function submit(values: AccountForm) {
    if (!account) {
      void editor.save(() => adminApi.createAdminAccount(values))
    } else if (values.role !== account.role) {
      void editor.save(() => adminApi.updateAdminRole(account.id, { role: values.role }))
    } else {
      editor.close()
    }
  }

  return (
    <Modal open title={account ? `修改角色 · ${account.username}` : '新建管理员账号'} okText="保存" cancelText="取消"
      onCancel={editor.close} onOk={form.submit}
      confirmLoading={editor.saving} cancelButtonProps={{ disabled: editor.saving }}
      closable={!editor.saving} maskClosable={false} keyboard={!editor.saving}
    >
      {editor.error && <Alert className="detail-note" type="error" showIcon message={editor.error} />}
      <Form<AccountForm> form={form} layout="vertical" initialValues={{ role: account?.role ?? 'operator' }}
        disabled={editor.saving} onFinish={submit}
      >
        {!account && (
          <>
            <Form.Item label="用户名" name="username" rules={[
              { required: true, pattern: /^\S+$/, max: 64, message: '请输入 1～64 个字符，且不要包含空白' },
            ]}>
              <Input maxLength={64} autoComplete="off" />
            </Form.Item>
            <Form.Item label="初始密码" name="password" rules={[
              { required: true, min: 12, max: 128, message: '请输入 12～128 字符的初始密码' },
            ]}>
              <Input.Password maxLength={128} autoComplete="new-password" />
            </Form.Item>
          </>
        )}
        <Form.Item label="角色" name="role" rules={[{ required: true, message: '请选择角色' }]}>
          <Select options={roleOptions} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function PasswordReset({ account, isSelf, onClose }: {
  account: Account; isSelf: boolean; onClose: (reset: boolean) => void
}) {
  const cache = useQueryClient()
  const sending = useRef(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [password, setPassword] = useState<string>()

  async function reset() {
    if (sending.current) return
    sending.current = true
    setPending(true)
    setError('')
    try {
      if (isSelf) await cache.cancelQueries({ queryKey: [resource] })
      const { temporary_password } = await adminApi.resetAdminPassword(account.id)
      setPassword(temporary_password)
      if (!isSelf) {
        void cache.invalidateQueries({ queryKey: [resource] })
        void cache.invalidateQueries({ queryKey: ['audit'] })
      }
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      sending.current = false
      setPending(false)
    }
  }

  function close() {
    if (!sending.current) onClose(password !== undefined)
  }

  return (
    <Modal open title={password ? '临时密码' : '重置密码'} maskClosable={false}
      keyboard={!pending} closable={!pending} onCancel={close}
      footer={password ? <Button type="primary" onClick={close}>关闭</Button> : undefined}
      okType="danger" okText="确认重置" cancelText="取消" onOk={() => { void reset() }}
      confirmLoading={pending} cancelButtonProps={{ disabled: pending }}
    >
      {password ? (
        <>
          <Alert className="detail-note" type="warning" showIcon message="请立即复制临时密码，关闭后将无法再次查看。"
            description="使用临时密码登录时必须设置新密码，登录成功后临时密码失效。" />
          <Typography.Text code copyable={{ text: password }} style={{ overflowWrap: 'anywhere' }}>{password}</Typography.Text>
        </>
      ) : (
        <>
          <p>重置「{account.username}」的密码将立即结束该账号的所有会话。</p>
          {isSelf && <p>复制临时密码并关闭弹窗后，请重新登录。</p>}
          {error && <Alert className="detail-note" type="error" showIcon message={error} />}
        </>
      )}
    </Modal>
  )
}

export default function Administrators() {
  const canWrite = usePermission('admin:write')
  const { state, check } = useSession()
  const currentId = state.status === 'ready' ? state.account.id : undefined
  const confirm = useConfirmChange(resource)
  const [editing, setEditing] = useState<Account | null>()
  const [resetting, setResetting] = useState<Account>()
  // 重置本账号会撤销当前会话，复制临时密码前暂停列表请求。
  const resettingSelf = resetting !== undefined && resetting.id === currentId
  const query = useCursorList(resource, (cursor, signal) => adminApi.adminAccounts({ cursor }, signal), 0, !resettingSelf)

  return (
    <>
      <PageHeading title="管理员账号" action={canWrite && (
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新建账号</Button>
      )} />
      <CursorTable<Account> query={query} rowKey="id" columns={[
        { title: '账号 ID', dataIndex: 'id' },
        { title: '用户名', dataIndex: 'username' },
        { title: '角色', render: (_, account) => <Tag>{adminRole[account.role]}</Tag> },
        { title: '状态', render: (_, account) => <Status value={account.status} labels={adminAccountStatus} /> },
        { title: '创建时间', dataIndex: 'created_at', render: dateText },
        { title: '最近修改', dataIndex: 'updated_at', render: dateText },
        ...(canWrite ? [{
          title: '操作',
          render: (_: unknown, account: Account) => (
            <Space>
              {account.id !== currentId && (
                <Button size="small" disabled={query.isFetching} onClick={() => setEditing(account)}>修改角色</Button>
              )}
              {account.status === 'active' && (
                <>
                  {account.id !== currentId && (
                    <Button size="small" danger disabled={query.isFetching} onClick={() => confirm({
                      title: '停用账号',
                      content: `确认停用「${account.username}」并结束该账号的所有会话？`,
                      okText: '确认停用',
                      okType: 'danger',
                    }, () => adminApi.disableAdminAccount(account.id), '已停用账号')}>停用</Button>
                  )}
                  <Button size="small" disabled={query.isFetching} onClick={() => setResetting(account)}>重置密码</Button>
                </>
              )}
            </Space>
          ),
        }] : []),
      ]} />
      {canWrite && editing !== undefined && <AccountEditor account={editing} onClose={() => setEditing(undefined)} />}
      {canWrite && resetting && (
        <PasswordReset account={resetting} isSelf={resettingSelf} onClose={(reset) => {
          setResetting(undefined)
          if (reset && resettingSelf) check()
        }} />
      )}
    </>
  )
}
