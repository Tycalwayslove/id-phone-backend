import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { createRender, getPhoto } from '../../api/photos'
import { getPreviewSpec, getSpec } from '../../api/specs'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PhotoFrame from '../../components/PhotoFrame'
import SpecPicker from '../../components/SpecPicker'
import UnlockSheet from '../../components/UnlockSheet'
import useCity from '../../hooks/useCity'
import useCommonSpecs from '../../hooks/useCommonSpecs'
import { describeError, handleError } from '../../utils/errors'
import { bgColorHex, bgColorName } from '../../utils/format'
import { PAGES, SPEC_PICKED_EVENT, buildUrl, navigate, redirect, toInt } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import { saveRenderToAlbum } from '../../utils/saveImage'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']
type PhotoDetail = components['schemas']['PhotoDetail']
type RenderOut = components['schemas']['RenderOut']

const WHITE = '#FFFFFF'
const FINE_MATTING_POLL_INTERVAL = 3000
const FINE_MATTING_POLL_TIMEOUT = 60000

interface EditorSettings {
  spec: SpecDetail
  confirmed: boolean
  bgColor: string
  beauty: number
  adjustments: string[]
}

/** 制作页。photo_id 必填，spec_code 有值时直接按所选证件制作。 */
export default function Editor() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const initialSpecCode = params.spec_code

  const [settings, setSettings] = useState<EditorSettings | null>(null)
  const [loadError, setLoadError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [photo, setPhoto] = useState<PhotoDetail | null>(null)
  const [render, setRender] = useState<RenderOut | null>(null)
  const [rendering, setRendering] = useState(false)
  const [quietRendering, setQuietRendering] = useState(false)
  const [renderFailed, setRenderFailed] = useState(false)
  const [pollingMatting, setPollingMatting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [unlockOpen, setUnlockOpen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [selectingSpec, setSelectingSpec] = useState(false)
  const [paymentConfirmed, setPaymentConfirmed] = useState(false)
  const { city, regionCode } = useCity()
  const common = useCommonSpecs(regionCode, { enabled: pickerOpen && city !== null })
  const photoSeq = useRef(0)
  const renderSeq = useRef(0)
  const savingRef = useRef(false)
  const selectingSpecRef = useRef(false)

  const spec = settings?.spec
  const specCode = spec?.code
  const confirmed = settings?.confirmed ?? false
  const bgColor = settings?.bgColor ?? WHITE
  const beauty = settings?.beauty ?? 0
  const active = photo?.access.active ?? false
  const originalUrl = photo?.original_url
  const mattingLevel = photo?.matting_level
  const fineMatting = mattingLevel === 'fine'
  // 仅限一种规格的权益会把第一张无水印成品锁定在该规格。
  const needsConfirmedSpec = !confirmed && active && !photo?.access.spec_change
  const request = useMemo(() => {
    if (!photoId || !specCode || needsConfirmedSpec) return null
    return { photoId, body: { spec_code: specCode, bg_color: bgColor, beauty_level: beauty } }
  }, [photoId, specCode, bgColor, beauty, needsConfirmedSpec])
  const lastRequest = useRef<{ request: typeof request; active: boolean; fine: boolean } | null>(null)

  const retake = useCallback(async () => {
    const replacement = await pickAndCreatePhoto('camera')
    if (replacement) await redirect(PAGES.editor, { photo_id: replacement.id, spec_code: confirmed ? specCode : undefined })
  }, [confirmed, specCode])

  const refreshPhoto = useCallback(async () => {
    if (!photoId) return null
    const seq = ++photoSeq.current
    const current = await getPhoto(photoId)
    if (seq === photoSeq.current) setPhoto(current)
    return current
  }, [photoId])

  useEffect(() => {
    if (!photoId) return
    let current = true
    setLoadError('')
    Promise.all([initialSpecCode ? getSpec(initialSpecCode) : getPreviewSpec(), refreshPhoto()])
      .then(([detail]) => {
        if (current) {
          setSettings({
            spec: detail,
            confirmed: Boolean(initialSpecCode),
            bgColor: detail.bg_colors[0] ?? WHITE,
            beauty: 0,
            adjustments: [],
          })
        }
      })
      .catch((e: unknown) => {
        if (current) setLoadError(describeError(e).message)
      })
    return () => {
      current = false
      photoSeq.current++
      renderSeq.current++
    }
  }, [photoId, initialSpecCode, refreshPhoto, loadAttempt])

  useDidShow(() => {
    if (!photo || unlockOpen || savingRef.current) return
    void refreshPhoto().catch(() => undefined)
  })
  useDidHide(() => setComparing(false))

  useEffect(() => {
    if (!photoId || mattingLevel !== 'fast') return
    let inFlight = false
    setPollingMatting(true)
    const interval = setInterval(() => {
      if (inFlight) return
      inFlight = true
      void refreshPhoto()
        .catch(() => undefined)
        .finally(() => { inFlight = false })
    }, FINE_MATTING_POLL_INTERVAL)
    const timeout = setTimeout(() => {
      clearInterval(interval)
      setPollingMatting(false)
    }, FINE_MATTING_POLL_TIMEOUT)
    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [mattingLevel, photoId, refreshPhoto])

  const doRender = useCallback(async (
    expectedActive: boolean, fine: boolean, quiet = false,
  ): Promise<RenderOut | null> => {
    if (!request) return null
    lastRequest.current = { request, active: expectedActive, fine }
    const seq = ++renderSeq.current
    setQuietRendering(quiet)
    setRendering(true)
    setRenderFailed(false)
    try {
      const result = await createRender(request.photoId, request.body)
      if (seq !== renderSeq.current) return null
      setRender(result)
      return result
    } catch (e) {
      if (seq === renderSeq.current) {
        setRenderFailed(true)
        if (!quiet) {
          setRender(null)
          await handleError(e, { photoId: request.photoId, onRetake: retake })
        }
      }
      return null
    } finally {
      if (seq === renderSeq.current) setRendering(false)
    }
  }, [request, retake])

  useEffect(() => {
    if (savingRef.current) return
    const previous = lastRequest.current
    const sameSettings = previous !== null && previous.request === request && previous.active === active
    if (sameSettings && previous.fine === fineMatting) return
    void doRender(active, fineMatting, sameSettings && fineMatting)
  }, [active, doRender, fineMatting, request, saving])

  useEffect(() => {
    // 审核通过后补取原图；看到无水印图时也同步可能已在别处获得的权益。
    if (render && (!originalUrl || (!active && !render.watermarked))) {
      void refreshPhoto().catch(() => undefined)
    }
  }, [active, originalUrl, refreshPhoto, render])

  async function selectSpec(code: string): Promise<void> {
    if (!settings || selectingSpecRef.current) return
    setPickerOpen(false)
    if (code === settings.spec.code) {
      setSettings({ ...settings, confirmed: true })
      return
    }
    selectingSpecRef.current = true
    setSelectingSpec(true)
    try {
      const nextSpec = await getSpec(code)
      const colors = nextSpec.bg_colors.length ? nextSpec.bg_colors : [WHITE]
      const retainedColor = colors.find((color) => bgColorHex(color) === bgColorHex(settings.bgColor))
      const nextColor = retainedColor ?? colors[0]
      const nextBeauty = Math.min(settings.beauty, nextSpec.beauty_max)
      const adjustments: string[] = []
      if (!retainedColor) {
        const name = bgColorName(nextColor)
        const color = name === '其他' ? bgColorHex(nextColor) : name
        adjustments.push(`${nextSpec.name}要求${color}底，已自动换成${color}底`)
      }
      if (nextBeauty < settings.beauty) {
        adjustments.push(nextBeauty === 0
          ? `${nextSpec.name}官方不允许美颜，已关闭`
          : `${nextSpec.name}最多允许 ${nextBeauty} 档美颜，已调到 ${nextBeauty} 档`)
      }
      renderSeq.current++
      setComparing(false)
      setRender(null)
      setRenderFailed(false)
      setSettings({ spec: nextSpec, confirmed: true, bgColor: nextColor, beauty: nextBeauty, adjustments })
    } catch (e) {
      await handleError(e)
    } finally {
      selectingSpecRef.current = false
      setSelectingSpec(false)
    }
  }

  async function save(refreshAccess = false): Promise<void> {
    if (!photoId || savingRef.current) return
    savingRef.current = true
    setSaving(true)
    try {
      let fine = fineMatting
      if (refreshAccess) {
        const updated = await refreshPhoto()
        if (!updated?.access.active) {
          await Taro.showToast({ title: '照片权益暂未生效，请稍后重试保存', icon: 'none' })
          return
        }
        setPaymentConfirmed(false)
        fine = updated.matting_level === 'fine'
      }
      // 保存时请求当前底片，覆盖轮询间隔内刚完成的精细抠图。
      const result = await doRender(true, fine)
      if (result?.watermarked === false) await saveRenderToAlbum(photoId, result.id)
      else if (result?.watermarked) {
        await Taro.showToast({ title: '高清照片还未生成，请重新生成', icon: 'none' })
      }
    } catch (e) {
      await handleError(e, { photoId, onRetake: retake })
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  if (!photoId) {
    return (
      <PageContainer>
        <View className='list-footer'>缺少参数，请返回重新选择</View>
      </PageContainer>
    )
  }
  if (!settings || !spec) {
    return (
      <PageContainer>
        {loadError ? (
          <View className='list-gap'>
            <Text className='hint'>{loadError}</Text>
            <Button className='btn-native btn-native--plain' onClick={() => setLoadAttempt((n) => n + 1)}>
              重新加载
            </Button>
          </View>
        ) : <Loading />}
      </PageContainer>
    )
  }

  const bgColors = spec.bg_colors.length > 0 ? [...new Set(spec.bg_colors)] : [WHITE]
  const ratio = spec.width_px / spec.height_px
  const width = Math.min(360, 440 * ratio)
  const previewUrl = needsConfirmedSpec ? originalUrl : render?.preview_url
  const compareReady = Boolean(!needsConfirmedSpec && render && originalUrl)
  const previewReady = render?.spec_code === spec.code &&
    render.bg_color === bgColor && render.beauty_level === beauty
  const matchesAccess = render?.watermarked === !active
  const blocked = unlockOpen || saving || pickerOpen || selectingSpec
  const canSave = !blocked && (!rendering || quietRendering) && (
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
          {previewUrl ? (
            <Image className='editor-preview__img' src={resolveUrl(previewUrl)} mode='aspectFit' />
          ) : null}
          {rendering && (!quietRendering || !previewUrl) && !needsConfirmedSpec ? (
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
        {mattingLevel === 'fast' && pollingMatting ? (
          <Text className='hint editor-preview__compare'>正在精细抠图，边缘会更干净</Text>
        ) : null}
        {compareReady ? <Text className='hint editor-preview__compare'>按住照片对比原图</Text> : null}
        {confirmed ? (
          <View className='editor-preview__details'>
            <Text className='editor-preview__name'>{spec.name}</Text>
            <Text className='hint'>{spec.width_px}×{spec.height_px} 像素</Text>
            <Button className='editor-preview__change' disabled={blocked} onClick={() => setPickerOpen(true)}>
              换一个
            </Button>
          </View>
        ) : (
          <Text className='hint editor-preview__details'>
            {needsConfirmedSpec ? '当前权益限用一种规格，选证件类型后生成成品' : '还没选证件类型，先把照片修满意'}
          </Text>
        )}
        {settings.adjustments.map((message) => <Text className='hint editor-preview__notice' key={message}>{message}</Text>)}
        {!needsConfirmedSpec && (renderFailed || (render && !matchesAccess)) && !rendering ? (
          <Button className='btn-native btn-native--plain' disabled={blocked} onClick={() => void doRender(active, fineMatting)}>
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
                onClick={() => setSettings((current) => current && { ...current, bgColor: color, adjustments: [] })}
              >
                <View className='editor-colors__swatch' style={{ background: bgColorHex(color) }} />
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
                    onClick={() => setSettings((current) => current && { ...current, beauty: level, adjustments: [] })}
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
        {confirmed ? (
          <>
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
          </>
        ) : (
          <View className='editor-bottom__actions'>
            <Button className='btn-native' disabled={blocked} onClick={() => setPickerOpen(true)}>
              选证件类型
            </Button>
          </View>
        )}
      </View>
      <SpecPicker
        open={pickerOpen}
        specs={common.specs}
        loading={common.loading}
        title='选证件类型'
        citySkipLabel='跳过，查看全国通用规格'
        onClose={() => setPickerOpen(false)}
        onPick={(item) => void selectSpec(item.code)}
        onSearch={() => {
          void Taro.navigateTo({
            url: buildUrl(PAGES.specs, { select: 1 }),
            events: { [SPEC_PICKED_EVENT]: (code: string) => void selectSpec(code) },
          }).catch(handleError)
        }}
      />
      {confirmed ? (
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
      ) : null}
    </PageContainer>
  )
}
