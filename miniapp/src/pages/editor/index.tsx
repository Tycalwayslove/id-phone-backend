import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { createRender, getPhoto } from '../../api/photos'
import { getSpec } from '../../api/specs'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PhotoFrame from '../../components/PhotoFrame'
import UnlockSheet from '../../components/UnlockSheet'
import { handleError } from '../../utils/errors'
import { bgColorName } from '../../utils/format'
import { PAGES, navigate, redirect, toInt } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import { saveRenderToAlbum } from '../../utils/saveImage'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']
type PhotoDetail = components['schemas']['PhotoDetail']
type RenderOut = components['schemas']['RenderOut']

const WHITE = '#FFFFFF'

/** 制作页。路由参数：photo_id、spec_code */
export default function Editor() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const specCode = params.spec_code ?? ''

  const [spec, setSpec] = useState<SpecDetail | null>(null)
  const [photo, setPhoto] = useState<PhotoDetail | null>(null)
  const [chosenBg, setChosenBg] = useState<string>()
  const [beauty, setBeauty] = useState(0)
  const [render, setRender] = useState<RenderOut | null>(null)
  const [rendering, setRendering] = useState(false)
  const [renderFailed, setRenderFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [unlockOpen, setUnlockOpen] = useState(false)
  const [paymentConfirmed, setPaymentConfirmed] = useState(false)
  const photoSeq = useRef(0)
  const renderSeq = useRef(0)
  const savingRef = useRef(false)

  const active = photo?.access.active ?? false
  const originalUrl = photo?.original_url
  const bgColor = chosenBg ?? spec?.bg_colors[0] ?? WHITE
  const request = useMemo(() => {
    if (!photoId || !spec) return null
    return { photoId, body: { spec_code: spec.code, bg_color: bgColor, beauty_level: beauty } }
  }, [photoId, spec, bgColor, beauty])
  const lastRequest = useRef<{ request: typeof request; active: boolean } | null>(null)

  const retake = useCallback(async () => {
    const replacement = await pickAndCreatePhoto('camera')
    if (replacement) await redirect(PAGES.editor, { photo_id: replacement.id, spec_code: specCode })
  }, [specCode])

  const refreshPhoto = useCallback(async () => {
    if (!photoId) return null
    const seq = ++photoSeq.current
    const current = await getPhoto(photoId)
    if (seq === photoSeq.current) setPhoto(current)
    return current
  }, [photoId])

  useEffect(() => {
    if (!photoId || !specCode) return
    let current = true
    Promise.all([getSpec(specCode), refreshPhoto()])
      .then(([detail]) => {
        if (current) setSpec(detail)
      })
      .catch((e: unknown) => {
        if (current) return handleError(e)
      })
    return () => {
      current = false
      photoSeq.current++
      renderSeq.current++
    }
  }, [photoId, specCode, refreshPhoto])

  useDidShow(() => {
    if (!photo || unlockOpen || savingRef.current) return
    void refreshPhoto().catch(() => undefined)
  })
  useDidHide(() => setComparing(false))

  const doRender = useCallback(async (expectedActive: boolean): Promise<RenderOut | null> => {
    if (!request) return null
    lastRequest.current = { request, active: expectedActive }
    const seq = ++renderSeq.current
    setRendering(true)
    setRenderFailed(false)
    try {
      const result = await createRender(request.photoId, request.body)
      if (seq !== renderSeq.current) return null
      setRender(result)
      return result
    } catch (e) {
      if (seq === renderSeq.current) {
        setRender(null)
        setRenderFailed(true)
        await handleError(e, { photoId: request.photoId, onRetake: retake })
      }
      return null
    } finally {
      if (seq === renderSeq.current) setRendering(false)
    }
  }, [request, retake])

  useEffect(() => {
    // 支付回调会直接生成可保存的图，权益状态更新时复用这次请求。
    if (lastRequest.current?.request === request && lastRequest.current.active === active) return
    void doRender(active)
  }, [active, doRender, request])

  useEffect(() => {
    // 审核通过后补取原图；看到无水印图时也同步可能已在别处获得的权益。
    if (render && (!originalUrl || (!active && !render.watermarked))) {
      void refreshPhoto().catch(() => undefined)
    }
  }, [active, originalUrl, refreshPhoto, render])

  async function save(refreshAccess = false): Promise<void> {
    if (!photoId || savingRef.current) return
    savingRef.current = true
    setSaving(true)
    try {
      let result = render
      if (refreshAccess) {
        const updated = await refreshPhoto()
        if (!updated?.access.active) {
          await Taro.showToast({ title: '照片权益暂未生效，请稍后重试保存', icon: 'none' })
          return
        }
        setPaymentConfirmed(false)
        result = await doRender(true)
      }
      if (result?.watermarked === false) await saveRenderToAlbum(photoId, result.id)
      else if (result?.watermarked) {
        await Taro.showToast({ title: '高清照片还未生成，请重新生成', icon: 'none' })
      }
    } catch (e) {
      await handleError(e, { photoId, onRetake: retake })
    } finally {
      setSaving(false)
      savingRef.current = false
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

  const bgColors = spec.bg_colors.length > 0 ? spec.bg_colors : [WHITE]
  const ratio = spec.width_px / spec.height_px
  const width = Math.min(360, 440 * ratio)
  const compareReady = Boolean(render && originalUrl)
  const previewReady = render?.spec_code === spec.code &&
    render.bg_color === bgColor && render.beauty_level === beauty
  const matchesAccess = render?.watermarked === !active
  const blocked = unlockOpen || saving
  const canSave = !blocked && !rendering && (
    paymentConfirmed || (previewReady && matchesAccess)
  )

  return (
    <PageContainer withBottomBar>
      <View className='editor-preview'>
        <PhotoFrame
          className='editor-preview__frame'
          style={{ width: Taro.pxTransform(width), height: Taro.pxTransform(width / ratio) }}
          onTouchStart={() => {
            if (compareReady) setComparing(true)
          }}
          onTouchEnd={() => setComparing(false)}
          onTouchCancel={() => setComparing(false)}
        >
          {render ? <Image className='editor-preview__img' src={resolveUrl(render.preview_url)} mode='aspectFit' /> : null}
          {rendering ? (
            <View className='editor-preview__mask'><Loading text='生成中…' /></View>
          ) : null}
          {compareReady && originalUrl ? (
            <Image
              className={`editor-preview__img editor-preview__original${comparing ? ' editor-preview__original--visible' : ''}`}
              src={resolveUrl(originalUrl)}
              mode='aspectFit'
            />
          ) : null}
        </PhotoFrame>
        {compareReady ? <Text className='hint editor-preview__compare'>按住照片对比原图</Text> : null}
        <View className='editor-preview__details'>
          <Text className='editor-preview__name'>{spec.name}</Text>
          <Text className='hint'>{spec.width_px}×{spec.height_px} 像素</Text>
          {previewReady ? <Text className='editor-preview__size'>符合官方尺寸</Text> : null}
        </View>
        {(renderFailed || (render && !matchesAccess)) && !rendering ? (
          <Button className='btn-native btn-native--plain' disabled={blocked} onClick={() => void doRender(active)}>
            重新生成
          </Button>
        ) : null}
      </View>

      <View className='card editor-options'>
        <View className='editor-options__row'>
          <Text className='editor-options__label'>底色</Text>
          <View className='editor-colors'>
            {bgColors.map((color) => (
              <Button
                key={color}
                className={`editor-colors__item${color === bgColor ? ' editor-colors__item--active' : ''}`}
                ariaLabel={`${bgColorName(color)}${color === bgColor ? '，已选中' : ''}`}
                disabled={blocked}
                onClick={() => setChosenBg(color)}
              >
                <View className='editor-colors__swatch' style={{ background: color }} />
                <Text>{bgColorName(color)}</Text>
              </Button>
            ))}
          </View>
        </View>
        <View className='editor-options__row'>
          <Text className='editor-options__label'>美颜</Text>
          {spec.beauty_max > 0 ? (
            <View className='editor-beauty'>
              <Text className='hint'>自然</Text>
              <View className='editor-beauty__levels'>
                {Array.from({ length: spec.beauty_max + 1 }, (_, level) => (
                  <Button
                    key={level}
                    className={`editor-beauty__level${level === beauty ? ' editor-beauty__level--active' : ''}`}
                    ariaLabel={`${level === 0 ? '自然，不美颜' : `美颜 ${level} 档`}${level === beauty ? '，已选中' : ''}`}
                    disabled={blocked}
                    onClick={() => setBeauty(level)}
                  >
                    <View className='editor-beauty__dot' />
                  </Button>
                ))}
              </View>
              <Text className='hint'>精致</Text>
            </View>
          ) : <Text className='hint'>该规格官方不允许美颜</Text>}
        </View>
      </View>

      <View className='bottom-bar editor-bottom'>
        {!active ? <Text className='hint'>预览带水印，保存后是高清无水印照片</Text> : null}
        <View className='editor-bottom__actions'>
          {spec.supports_receipt ? (
            <Button
              className='btn-native btn-native--plain editor-bottom__receipt'
              disabled={blocked}
              onClick={() => navigate(PAGES.receiptApply, { photo_id: photoId, spec_code: spec.code })}
            >
              办理回执
            </Button>
          ) : null}
          <Button className='btn-native' disabled={!canSave} loading={saving} onClick={() => {
            if (paymentConfirmed || active) void save(paymentConfirmed)
            else setUnlockOpen(true)
          }}>
            保存高清照片
          </Button>
        </View>
      </View>
      <UnlockSheet
        open={unlockOpen}
        photoId={photoId}
        supportsReceipt={spec.supports_receipt}
        onClose={() => setUnlockOpen(false)}
        onPaid={async () => {
          setUnlockOpen(false)
          setPaymentConfirmed(true)
          await save(true)
        }}
      />
    </PageContainer>
  )
}
