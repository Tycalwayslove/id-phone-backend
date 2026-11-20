import { IdcardOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input } from 'antd'
import { useRef, useState } from 'react'
import { ApiError, errorText, type Schema } from '../api/client'
import { useSession } from '../session'

const passwordChangeMessage = '请设置与临时密码不同的正式密码'

export default function Login() {
  const { login } = useSession()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [mustChangePassword, setMustChangePassword] = useState(false)
  const sending = useRef(false)
  const [form] = Form.useForm<Schema['AdminLoginIn']>()

  async function submit(values: Schema['AdminLoginIn']) {
    if (sending.current) return
    sending.current = true
    setPending(true)
    setError('')
    try {
      await login(mustChangePassword ? values : { username: values.username, password: values.password })
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 422
        && failure.code === 'VALIDATION_ERROR' && failure.message === passwordChangeMessage) {
        setMustChangePassword(true)
        form.setFieldValue('new_password', '')
      } else {
        if (!mustChangePassword || (failure instanceof ApiError && failure.code === 'ADMIN_LOGIN_FAILED')) {
          form.setFieldValue('password', '')
          setMustChangePassword(false)
        }
        setError(errorText(failure))
      }
    } finally {
      sending.current = false
      setPending(false)
    }
  }

  return (
    <main className="login">
      <div className="login-panel">
        <div className="login-brand"><IdcardOutlined /> 智拍证件照</div>
        <h1>{mustChangePassword ? '设置新密码' : '登录运营后台'}</h1>
        {mustChangePassword && <Alert type="info" showIcon message="使用临时密码登录前，请设置一个不同的正式密码。" />}
        {error && <Alert type="error" showIcon message={error} />}
        <Form<Schema['AdminLoginIn']>
          form={form} layout="vertical" size="large" disabled={pending}
          requiredMark={false} onFinish={(values) => { void submit(values) }}
        >
          <Form.Item label="账号" name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input autoComplete="username" maxLength={64} autoFocus readOnly={mustChangePassword} />
          </Form.Item>
          <Form.Item label={mustChangePassword ? '临时密码' : '密码'} name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" maxLength={128} readOnly={mustChangePassword} />
          </Form.Item>
          {mustChangePassword && (
            <Form.Item label="新密码" name="new_password" preserve={false} dependencies={['password']} rules={[
              { required: true, min: 12, max: 128, message: '请输入 12～128 字符的新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value: string) => value !== getFieldValue('password')
                  ? Promise.resolve() : Promise.reject(new Error('新密码须与临时密码不同')),
              }),
            ]}>
              <Input.Password autoComplete="new-password" maxLength={128} autoFocus />
            </Form.Item>
          )}
          <Button type="primary" htmlType="submit" block loading={pending}>{mustChangePassword ? '设置新密码并登录' : '登录'}</Button>
          {mustChangePassword && <Button type="link" block onClick={() => {
            form.setFieldValue('password', '')
            setError('')
            setMustChangePassword(false)
          }}>返回登录</Button>}
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
