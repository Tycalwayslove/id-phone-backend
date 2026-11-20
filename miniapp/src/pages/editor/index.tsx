import { useCallback, useEffect, useRef, useState } from 'react'
import { Image, Slider, Text, View } from '@tarojs/components'
import { useDidShow, useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { createRender, getPhoto } from '../../api/photos'
import { getSpec } from '../../api/specs'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { handleError } from '../../utils/errors'
import { PAGES, navigate, redirect, toInt } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import { saveRenderToAlbum } from '../../utils/saveImage'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']
type PhotoDetail = components['schemas']['PhotoDetail']
type RenderOut = components['schemas']['RenderOut']

/** 制作页。路由参数：photo_id、spec_code */
export default function Editor() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const specCode = params.spec_code ?? ''

  const [spec, setSpec] = useState<SpecDetail | null>(null)
  const [access, setAccess] = useState<PhotoDetail['access'] | null>(null)
  const [bgColor, setBgColor] = useState('')
  const [beauty, setBeauty] = useState(0)
  const [render, setRender] = useState<RenderOut | null>(null)
  const [rendering, setRendering] = useState(false)
  const [renderFailed, setRenderFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const seqRef = useRef(0)
  const loadedRef = useRef(false)

  const retake = useCallback(async () => {
    const photo = await pickAndCreatePhoto('camera')
    if (photo) await redirect(PAGES.editor, { photo_id: photo.id, spec_code: specCode })
  }, [specCode])

  // 规格 + 权益
  useEffect(() => {
    if (!photoId || !specCode) return
    Promise.all([getSpec(specCode), getPhoto(photoId)])
      .then(([s, p]) => {
        setSpec(s)
        setAccess(p.access)
        setBgColor(s.bg_colors[0] ?? '')
        loadedRef.current = true
      })
      .catch((e: unknown) => handleError(e))
  }, [photoId, specCode])

  // 从购买页返回时刷新权益
  useDidShow(() => {
    if (!loadedRef.current || !photoId) return
    getPhoto(photoId)
      .then((p) => setAccess(p.access))
      .catch(() => undefined)
  })

  const active = access?.active ?? false

  // 底色、美颜、权益变化后重新生成；seq 丢弃过期结果
  const doRender = useCallback(async () => {
    if (!photoId || !spec || !bgColor) return
    const seq = ++seqRef.current
    setRendering(true)
    setRenderFailed(false)
    try {
      const r = await createRender(photoId, { spec_code: spec.code, bg_color: bgColor, beauty_level: beauty })
      if (seq === seqRef.current) setRender(r)
    } catch (e) {
      if (seq === seqRef.current) {
        setRender(null)
        setRenderFailed(true)
        await handleError(e, { photoId, onRetake: retake })
      }
    } finally {
      if (seq === seqRef.current) setRendering(false)
    }
  }, [photoId, spec, bgColor, beauty, active, retake])

  useEffect(() => {
    void doRender()
  }, [doRender])

  async function save(): Promise<void> {
    if (!photoId || !render || saving) return
    setSaving(true)
    try {
      await saveRenderToAlbum(photoId, render.id)
    } catch (e) {
      await handleError(e, { photoId, onRetake: retake })
    } finally {
      setSaving(false)
    }
  }

  if (!photoId || !specCode) {
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

  const canSave = active && render !== null && !render.watermarked
  const ratio = spec.height_px / spec.width_px

  return (
    <PageContainer withBottomBar>
      <View className='card editor-preview'>
        <View className='editor-preview__box' style={{ paddingBottom: `${Math.round(ratio * 100)}%` }}>
          {render ? (
            <Image className='editor-preview__img' src={resolveUrl(render.preview_url)} mode='aspectFit' />
          ) : null}
          {rendering ? (
            <View className='editor-preview__mask'>
              <Loading text='生成中…' />
            </View>
          ) : null}
        </View>
        <Text className='editor-preview__spec'>
          {spec.name} · {spec.width_px}×{spec.height_px}px
        </Text>
        {render?.watermarked ? <Text className='editor-preview__tip'>购买后去除水印</Text> : null}
        {renderFailed && !rendering ? (
          <Button block type='default' onClick={doRender}>重新生成</Button>
        ) : null}
      </View>

      <View className='card'>
        <Text className='editor-label'>底色</Text>
        <View className='editor-colors'>
          {spec.bg_colors.map((c) => (
            <View
              key={c}
              className={`editor-colors__item${c === bgColor ? ' editor-colors__item--active' : ''}`}
              style={{ background: c }}
              onClick={() => setBgColor(c)}
            />
          ))}
        </View>

        {spec.beauty_max > 0 ? (
          <>
            <Text className='editor-label editor-label--gap'>美颜（0 为不美颜）</Text>
            <Slider
              min={0}
              max={spec.beauty_max}
              step={1}
              value={beauty}
              showValue
              activeColor='#2B6BFF'
              onChange={(e) => setBeauty(e.detail.value)}
            />
          </>
        ) : null}
      </View>

      <View className='bottom-bar'>
        {spec.supports_receipt ? (
          <Button
            block
            type='default'
            onClick={() => navigate(PAGES.receiptApply, { photo_id: photoId, spec_code: spec.code })}
          >
            办理回执
          </Button>
        ) : null}
        {active ? (
          <Button block type='primary' disabled={!canSave} loading={saving} onClick={save}>
            保存到相册
          </Button>
        ) : (
          <Button block type='primary' onClick={() => navigate(PAGES.plans, { photo_id: photoId })}>
            购买套餐
          </Button>
        )}
      </View>
    </PageContainer>
  )
}
