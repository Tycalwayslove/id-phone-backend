import { useCallback, useEffect, useRef, useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { ApiError, resolveUrl } from '../../api/client'
import { cancelReceipt, devSimulateReceipt, getReceipt, resubmitReceipt } from '../../api/receipts'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import StatusTag from '../../components/StatusTag'
import { handleError } from '../../utils/errors'
import { formatDate, formatDateTime } from '../../utils/format'
import { createKeyKeeper } from '../../utils/idempotency'
import { PAGES, navigate } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import type { PhotoSource } from '../../utils/pickPhoto'
import { FAKE_PAY_ENABLED } from '../../utils/status'
import './index.scss'

type ApplicationOut = components['schemas']['ApplicationOut']

/** 表单字段名 → 中文（未知字段原样显示） */
const FORM_LABELS: Record<string, string> = { name: '姓名', idcard: '身份证号', city: '城市', phone: '手机号' }

/** 回执详情页。路由参数：app_no */
export default function ReceiptDetail() {
  const { params } = useRouter()
  const appNo = params.app_no ?? ''
  const [app, setApp] = useState<ApplicationOut | null>(null)
  const [busy, setBusy] = useState(false)
  const keeper = useRef(createKeyKeeper())

  const load = useCallback(async () => {
    if (!appNo) return
    try {
      setApp(await getReceipt(appNo))
    } catch (e) {
      await handleError(e)
    }
  }, [appNo])

  // 每次显示都刷新（receipt_url 约 10 分钟过期）
  useDidShow(() => {
    void load()
  })

  // 办理中每 5 秒刷新一次状态
  const status = app?.status
  useEffect(() => {
    if (status !== 'pending' && status !== 'processing') return
    const timer = setInterval(() => {
      getReceipt(appNo)
        .then(setApp)
        .catch(() => undefined)
    }, 5000)
    return () => clearInterval(timer)
  }, [status, appNo])

  async function run(fn: () => Promise<ApplicationOut>): Promise<void> {
    if (busy) return
    setBusy(true)
    try {
      setApp(await fn())
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.code !== 'IDEMPOTENCY_CONFLICT') {
        keeper.current.release()
      }
      await handleError(e, { photoId: app?.photo_id })
    } finally {
      setBusy(false)
    }
  }

  async function resubmit(): Promise<void> {
    if (!app || busy) return
    const sheet = await Taro.showActionSheet({ itemList: ['使用原照片重新提交', '换一张照片（拍照）', '换一张照片（相册）'] }).catch(
      () => null
    )
    if (!sheet) return
    let photoId: number | undefined
    if (sheet.tapIndex > 0) {
      const source: PhotoSource = sheet.tapIndex === 1 ? 'camera' : 'upload'
      try {
        const photo = await pickAndCreatePhoto(source)
        if (!photo) return
        photoId = photo.id
      } catch (e) {
        await handleError(e)
        return
      }
    }
    const key = keeper.current.get(`${app.app_no}|${photoId ?? 'same'}|${app.resubmit_count}`)
    await run(async () => {
      const r = await resubmitReceipt(app.app_no, { photo_id: photoId }, key)
      keeper.current.release()
      return r
    })
  }

  async function cancel(): Promise<void> {
    if (!app) return
    const r = await Taro.showModal({ title: '取消办理', content: '确定取消这次回执办理吗？', confirmColor: '#FF3141' })
    if (!r.confirm) return
    await run(() => cancelReceipt(app.app_no))
  }

  async function copyCode(code: string): Promise<void> {
    await Taro.setClipboardData({ data: code })
  }

  if (!app) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }

  const rejected = app.status === 'rejected'

  return (
    <PageContainer withBottomBar={rejected}>
      <View className='card'>
        <View className='rd-head'>
          <Text className='rd-head__name'>{app.spec_name}</Text>
          <StatusTag kind='application' status={app.status} />
        </View>
        <Text className='hint'>申请单号 {app.app_no}</Text>
        <Text className='hint rd-line'>申请时间 {formatDateTime(app.created_at)}</Text>
        {app.status === 'pending' || app.status === 'processing' ? (
          <Text className='rd-wait'>办理中，出结果后会通知你，也可以下拉本页查看最新状态。</Text>
        ) : null}
      </View>

      {app.status === 'completed' ? (
        <View className='card'>
          <Text className='rd-title'>官方回执</Text>
          {app.receipt_url ? (
            <Image
              className='rd-receipt'
              src={resolveUrl(app.receipt_url)}
              mode='widthFix'
              onClick={() => Taro.previewImage({ urls: [resolveUrl(app.receipt_url ?? '')] })}
            />
          ) : null}
          {app.image_code ? (
            <View className='rd-code'>
              <View>
                <Text className='hint'>图像号</Text>
                <Text className='rd-code__value'>{app.image_code}</Text>
              </View>
              <View className='rd-code__copy' onClick={() => copyCode(app.image_code ?? '')}>
                复制
              </View>
            </View>
          ) : null}
          {app.official_expire_at ? <Text className='hint'>官方有效期至 {formatDate(app.official_expire_at)}</Text> : null}
        </View>
      ) : null}

      {rejected ? (
        <View className='card'>
          <Text className='rd-title rd-title--danger'>已被驳回</Text>
          <Text className='rd-reason'>{app.reject_reason || '请更换照片后重新提交'}</Text>
          <Text className='hint'>
            还可重新提交 {app.resubmit_left} 次（已重提 {app.resubmit_count} 次）
          </Text>
          {app.resubmit_left === 0 ? (
            <View className='rd-contact'>
              <Text className='hint'>重提次数已用完，请联系客服处理</Text>
              <Button openType='contact' className='btn-native btn-native--plain'>
                联系客服
              </Button>
            </View>
          ) : null}
        </View>
      ) : null}

      <View className='card'>
        <Text className='rd-title'>办理信息</Text>
        {Object.keys(app.form_masked).map((k) => (
          <View key={k} className='rd-kv'>
            <Text className='hint'>{FORM_LABELS[k] ?? k}</Text>
            <Text>{app.form_masked[k]}</Text>
          </View>
        ))}
      </View>

      <View className='card'>
        <Text className='rd-title'>提交记录</Text>
        <View className='rd-timeline'>
          {app.attempts.map((a) => (
            <View key={a.seq} className='rd-timeline__item'>
              <View className='rd-timeline__dot' />
              <View className='rd-timeline__body'>
                <View className='rd-timeline__row'>
                  <Text>第 {a.seq} 次提交</Text>
                  <StatusTag kind='attempt' status={a.status} />
                </View>
                <Text className='hint'>
                  {a.finished_at ? formatDateTime(a.finished_at) : formatDateTime(a.submitted_at) || '等待提交'}
                </Text>
                {a.reject_reason ? <Text className='rd-timeline__reason'>{a.reject_reason}</Text> : null}
              </View>
            </View>
          ))}
        </View>
      </View>

      {FAKE_PAY_ENABLED ? (
        <View className='rd-dev'>
          <Text className='hint'>开发：模拟结果</Text>
          <View className='rd-dev__btns'>
            <Text className='rd-dev__btn' onClick={() => run(() => devSimulateReceipt(app.app_no, { result: 'completed' }))}>
              completed
            </Text>
            <Text className='rd-dev__btn' onClick={() => run(() => devSimulateReceipt(app.app_no, { result: 'rejected' }))}>
              rejected
            </Text>
          </View>
        </View>
      ) : null}

      {rejected ? (
        <View className='bottom-bar'>
          <Button block type='default' disabled={busy} onClick={cancel}>
            取消办理
          </Button>
          <Button block type='primary' disabled={busy || app.resubmit_left === 0} onClick={resubmit}>
            重新提交
          </Button>
        </View>
      ) : null}

      {app.status === 'completed' ? (
        <View className='rd-footer-link' onClick={() => navigate(PAGES.photoDetail, { id: app.photo_id })}>
          查看这张照片 &gt;
        </View>
      ) : null}
    </PageContainer>
  )
}
