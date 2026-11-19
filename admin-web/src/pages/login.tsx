import { IdcardOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input } from 'antd'
import { useRef, useState } from 'react'
import { errorText, type Schema } from '../api/client'
import { useSession } from '../session'

export default function Login() {
  const { login } = useSession()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const sending = useRef(false)
  const [form] = Form.useForm<Schema['AdminLoginIn']>()

  async function submit(values: Schema['AdminLoginIn']) {
    if (sending.current) return
    sending.current = true
    setPending(true)
    setError('')
    try {
      await login(values)
    } catch (failure) {
      form.setFieldValue('password', '')
      setError(errorText(failure))
    } finally {
      sending.current = false
      setPending(false)
    }
  }

  return (
    <main className="login">
      <div className="login-panel">
        <div className="login-brand"><IdcardOutlined /> 智拍证件照</div>
        <h1>登录运营后台</h1>
        {error && <Alert type="error" showIcon message={error} />}
        <Form<Schema['AdminLoginIn']>
          form={form} layout="vertical" size="large" disabled={pending}
          requiredMark={false} onFinish={(values) => { void submit(values) }}
        >
          <Form.Item label="账号" name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input autoComplete="username" maxLength={64} autoFocus />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" maxLength={128} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={pending}>登录</Button>
        </Form>
      </div>
      <div className="login-aside" aria-hidden="true">
        <div className="portrait-guides">
          <div className="portrait-crop"><IdcardOutlined /></div>
        </div>
      </div>
    </main>
  )
}
