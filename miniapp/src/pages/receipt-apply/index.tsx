import { useEffect, useRef, useState } from 'react'
import { Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { ApiError } from '../../api/client'
import { listTemplates, reportSubscriptions } from '../../api/notify'
import { createReceipt } from '../../api/receipts'
import { getSpec } from '../../api/specs'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { handleError } from '../../utils/errors'
import { createKeyKeeper } from '../../utils/idempotency'
import { PAGES, redirect, toInt } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import { isIdCard18 } from '../../utils/validators'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']
type TemplateOut = components['schemas']['TemplateOut']
type ApplicationOut = components['schemas']['ApplicationOut']

const IS_WEAPP = Taro.getEnv() === Taro.ENV_TYPE.WEAPP

/**
 * 请求订阅消息授权，返回用户点了“允许”的模板 ID。
 * 必须在点击事件里同步调用（前面不能有 await），所以模板列表在页面加载时预取。
 */
async function askSubscribe(templates: TemplateOut[]): Promise<string[]> {
  if (!IS_WEAPP || templates.length === 0) return []
  try {
    const res = await Taro.requestSubscribeMessage({
      tmplIds: templates.map((t) => t.template_id),
      entityIds: [], // 支付宝小程序用的字段，微信忽略
    })
    return templates.map((t) => t.template_id).filter((id) => (res as unknown as Record<string, unknown>)[id] === 'accept')
  } catch {
    // 用户拒绝或弹窗异常都不影响提交
    return []
  }
}

/** 回执办理页。路由参数：photo_id、spec_code */
export default function ReceiptApply() {
  const { params } = useRouter()
  const specCode = params.spec_code ?? ''

  const [replacementId, setReplacementId] = useState<number>()
  const [spec, setSpec] = useState<SpecDetail | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [templates, setTemplates] = useState<TemplateOut[]>([])
  const [submitting, setSubmitting] = useState(false)
  const keeper = useRef(createKeyKeeper())
  const photoId = replacementId ?? toInt(params.photo_id)

  useEffect(() => {
    if (!specCode) return
    getSpec(specCode)
      .then(setSpec)
      .catch((e: unknown) => handleError(e))
    // 预取订阅模板；失败不阻塞办理
    if (IS_WEAPP) {
      listTemplates()
        .then(setTemplates)
        .catch(() => undefined)
    }
  }, [specCode])

  function validate(s: SpecDetail): string | null {
    for (const f of s.form_schema) {
      const v = (form[f.key] ?? '').trim()
      if (f.required && !v) return `请填写${f.label}`
      if (f.key === 'idcard' && v && !isIdCard18(v)) return '请输入 18 位身份证号'
    }
    return null
  }

  async function submit(): Promise<void> {
    if (!spec || photoId === undefined || submitting) return
    const problem = validate(spec)
    if (problem) {
      void Taro.showToast({ title: problem, icon: 'none' })
      return
    }
    setSubmitting(true)
    // 先授权订阅（紧跟点击，中间没有 await 网络请求）
    const accepted = await askSubscribe(templates)
    try {
      if (accepted.length) await reportSubscriptions(accepted).catch(() => undefined)
      const clean: Record<string, string> = {}
      spec.form_schema.forEach((f) => {
        const v = (form[f.key] ?? '').trim()
        if (v) clean[f.key] = v
      })
      // 同一份表单重复点击用同一个幂等键
      const key = keeper.current.get(`${photoId}|${spec.code}|${JSON.stringify(clean)}`)
      let app: ApplicationOut
      try {
        app = await createReceipt(
          { photo_id: photoId, spec_code: spec.code, form: clean, region_code: spec.region_code ?? undefined },
          key
        )
      } catch (e) {
        if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.code !== 'IDEMPOTENCY_CONFLICT') {
          keeper.current.release()
        }
        throw e
      }
      keeper.current.release()
      await redirect(PAGES.receiptDetail, { app_no: app.app_no })
    } catch (e) {
      await handleError(e, {
        photoId,
        onRetake: async () => {
          const photo = await pickAndCreatePhoto('camera')
          if (photo) setReplacementId(photo.id)
        }
      })
    } finally {
      setSubmitting(false)
    }
  }

  if (photoId === undefined || !specCode) {
    return (
      <PageContainer>
        <View className='list-footer'>缺少参数，请返回重新选择</View>
      </PageContainer>
    )
  }
  if (!spec) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }

  return (
    <PageContainer withBottomBar>
      <View className='card'>
        <Text className='apply-title'>{spec.name}</Text>
        {spec.form_schema.map((f) => (
          <View key={f.key} className='apply-field'>
            <Text className='apply-field__label'>
              {f.label}
              {f.required ? <Text className='apply-field__req'> *</Text> : null}
            </Text>
            <Input
              className='apply-field__input'
              type={f.key === 'idcard' ? 'idcard' : 'text'}
              maxlength={f.key === 'idcard' ? 18 : 50}
              placeholder={`请输入${f.label}`}
              value={form[f.key] ?? ''}
              onInput={(e) => {
                const v = e.detail.value
                setForm((prev) => ({ ...prev, [f.key]: v }))
              }}
            />
          </View>
        ))}
      </View>
      <Text className='hint apply-note'>
        信息仅用于办理官方照片回执，平台加密保存，不会用于其他用途。提交时会请求订阅消息授权，用于结果通知。
      </Text>
      {replacementId !== undefined ? (
        <Text className='hint apply-note'>已更换照片，请提交办理。</Text>
      ) : null}
      <View className='bottom-bar'>
        <Button block type='primary' loading={submitting} onClick={submit}>
          提交办理
        </Button>
      </View>
    </PageContainer>
  )
}
