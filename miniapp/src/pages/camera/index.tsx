import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Camera, Image, Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useReady, useRouter, useUnload } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { handleError } from '../../utils/errors'
import { GUIDE_HINT, GUIDE_LIMITS, stabilizeGuide, type GuideHint, type GuideStability } from '../../utils/faceGuide'
import { PAGES, goBack, redirect } from '../../utils/nav'
import { getPhotoQualityFeedback } from '../../utils/photoQuality'
import { createPhotoFromFile, pickPhotoFile, type PhotoSource } from '../../utils/pickPhoto'
import useFrontFillLight from './useFrontFillLight'
import useLiveFaceGuide from './useLiveFaceGuide'
import './index.scss'

type PhotoOut = components['schemas']['PhotoOut']
type CameraState = 'loading' | 'allowed' | 'denied' | 'unavailable'
type CountdownMode = 'manual' | 'auto'
const AUTO_CAPTURE_KEY = 'camera_auto_capture'

interface Draft {
  path: string
  source: PhotoSource
  photo?: PhotoOut
}

function takePhoto(): Promise<string> {
  return new Promise((resolve, reject) => {
    Taro.createCameraContext().takePhoto({
      quality: 'high',
      success: ({ tempImagePath }) => resolve(tempImagePath),
      fail: reject
    })
  })
}

function readAutoCapture(): boolean {
  try {
    return Taro.getStorageSync(AUTO_CAPTURE_KEY) !== false
  } catch {
    return true
  }
}

export default function CameraPage() {
  const { params } = useRouter()
  const weapp = Taro.getEnv() === Taro.ENV_TYPE.WEAPP
  const [albumOnly, setAlbumOnly] = useState(params.album === '1')
  const [cameraState, setCameraState] = useState<CameraState>('loading')
  const [visible, setVisible] = useState(true)
  const [ready, setReady] = useState(false)
  const [devicePosition, setDevicePosition] = useState<'front' | 'back'>('front')
  const [timerEnabled, setTimerEnabled] = useState(true)
  const [autoEnabled, setAutoEnabled] = useState(readAutoCapture)
  const [fillLight, setFillLight] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [guideHint, setGuideHint] = useState<GuideHint | null>(null)
  const [busy, setBusy] = useState(false)
  const [pickingAlbum, setPickingAlbum] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const locked = useRef(false)
  const alive = useRef(true)
  const focused = useRef(true)
  const captureVersion = useRef(0)
  const timeout = useRef<ReturnType<typeof setTimeout>>()
  const countdownMode = useRef<CountdownMode>()
  const guideStability = useRef<GuideStability | null>(null)
  const goodSince = useRef<number>()
  const lastGood = useRef<number>()

  const live = weapp && !albumOnly && cameraState === 'allowed' && !draft
  const showFeed = live && visible && !pickingAlbum
  const frontFill = live && fillLight && devicePosition === 'front'
  useFrontFillLight(frontFill && showFeed)
  // 手动倒计时停止取帧。自动倒计时继续校验姿态，界面暂停更新提示。
  const stopGuide = useLiveFaceGuide(showFeed && ready && !busy && countdownMode.current !== 'manual',
    devicePosition === 'front', onGuideSample)

  function clearCountdown(): void {
    clearTimeout(timeout.current)
    timeout.current = undefined
    countdownMode.current = undefined
    goodSince.current = undefined
    lastGood.current = undefined
  }

  function cancelCountdown(): void {
    clearCountdown()
    setCountdown(0)
  }

  function resetGuide(): void {
    guideStability.current = null
    goodSince.current = undefined
    lastGood.current = undefined
    setGuideHint(null)
  }

  function stopLiveGuide(): void {
    stopGuide()
    resetGuide()
  }

  function toggleAutoCapture(): void {
    const next = !autoEnabled
    goodSince.current = undefined
    lastGood.current = undefined
    setAutoEnabled(next)
    try {
      Taro.setStorageSync(AUTO_CAPTURE_KEY, next)
    } catch {
      // 本地存储不可用时，本次切换仍然生效。
    }
  }

  useDidShow(() => {
    focused.current = true
    setVisible(true)
  })
  useDidHide(() => {
    focused.current = false
    captureVersion.current++
    cancelCountdown()
    resetGuide()
    setReady(false)
    setVisible(false)
  })
  useUnload(() => {
    alive.current = false
    clearCountdown()
  })

  const requestPermission = useCallback(async () => {
    setCameraState('loading')
    try {
      await Taro.authorize({ scope: 'scope.camera' })
      if (alive.current) setCameraState('allowed')
    } catch {
      if (alive.current) setCameraState('denied')
    }
  }, [])

  useEffect(() => {
    if (weapp && !albumOnly) void requestPermission()
  }, [weapp, albumOnly, requestPermission])

  async function run(action: () => Promise<void>): Promise<void> {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    try {
      await action()
    } catch (e) {
      if (alive.current) await handleError(e)
    } finally {
      locked.current = false
      if (alive.current) setBusy(false)
    }
  }

  async function openAlbum(backOnCancel = false): Promise<void> {
    await run(async () => {
      cancelCountdown()
      stopLiveGuide()
      setReady(false)
      setPickingAlbum(true)
      try {
        const path = await pickPhotoFile('upload')
        if (!alive.current) return
        if (path) setDraft({ path, source: 'upload' })
        else if (backOnCancel) await goBack()
      } finally {
        if (alive.current) setPickingAlbum(false)
      }
    })
  }

  useReady(() => {
    if (weapp && albumOnly) void openAlbum(true)
  })

  async function openCameraSettings(): Promise<void> {
    await run(async () => {
      const { authSetting } = await Taro.openSetting()
      if (alive.current && authSetting['scope.camera']) setCameraState('allowed')
    })
  }

  async function onCameraError(): Promise<void> {
    cancelCountdown()
    stopLiveGuide()
    setReady(false)
    const setting = await Taro.getSetting().catch(() => undefined)
    if (alive.current) {
      setCameraState(setting?.authSetting['scope.camera'] === false ? 'denied' : 'unavailable')
    }
  }

  function stopCamera(): void {
    cancelCountdown()
    stopLiveGuide()
    setReady(false)
    if (focused.current && !locked.current) setCameraState('unavailable')
  }

  async function capture(): Promise<void> {
    if (!focused.current || locked.current) return
    cancelCountdown()
    resetGuide()
    const version = captureVersion.current
    await run(async () => {
      let path: string
      try {
        path = await takePhoto()
      } catch {
        if (alive.current && captureVersion.current === version) {
          await Taro.showToast({ title: '拍照失败，请再试一次', icon: 'none' })
        }
        return
      }
      if (alive.current && captureVersion.current === version) {
        setReady(false)
        setDraft({ path, source: 'camera' })
      }
    })
  }

  function beginCountdown(mode: CountdownMode): void {
    countdownMode.current = mode
    if (mode === 'manual') stopLiveGuide()
    function tick(seconds: number): void {
      setCountdown(seconds)
      timeout.current = setTimeout(() => {
        if (mode === 'auto' && Date.now() - (lastGood.current ?? -Infinity) > GUIDE_LIMITS.maxSampleAge) {
          cancelCountdown()
          resetGuide()
        } else if (seconds > 1) tick(seconds - 1)
        else void capture()
      }, 1000)
    }
    tick(3)
  }

  function startCapture(): void {
    if (!ready || !focused.current || locked.current) return
    if (countdownMode.current || !timerEnabled) void capture()
    else beginCountdown('manual')
  }

  function onGuideSample(hint: GuideHint | null, at: number): void {
    const mode = countdownMode.current
    if (!alive.current || !focused.current || locked.current || mode === 'manual') return
    const previousGood = lastGood.current
    const good = hint === 'good' && Date.now() - at <= GUIDE_LIMITS.maxSampleAge
    if (good) {
      if (previousGood === undefined || at - previousGood > GUIDE_LIMITS.maxSampleAge) goodSince.current = at
      lastGood.current = at
    } else {
      goodSince.current = undefined
      lastGood.current = undefined
    }

    if (mode === 'auto') {
      if (good && previousGood !== undefined && at - previousGood <= GUIDE_LIMITS.maxSampleAge) return
      cancelCountdown()
      resetGuide()
    }
    if (hint === null || (hint === 'good' && !good)) {
      resetGuide()
      return
    }
    const previous = guideStability.current
    const next = stabilizeGuide(previous, hint, at)
    guideStability.current = next
    if (next.shown !== previous?.shown) setGuideHint(next.shown)
    if (autoEnabled && goodSince.current !== undefined && at - goodSince.current >= GUIDE_LIMITS.autoDelay) {
      beginCountdown('auto')
    }
  }

  async function usePhoto(current: Draft, acceptFailed = false): Promise<void> {
    await run(async () => {
      const photo = current.photo ?? await createPhotoFromFile(current.path, current.source)
      if (!alive.current) return
      setDraft({ ...current, photo })
      const quality = getPhotoQualityFeedback(photo)
      if (focused.current && (quality?.level !== 'fail' || acceptFailed)) {
        await redirect(PAGES.editor, { photo_id: photo.id, spec_code: params.spec_code })
      }
    })
  }

  if (draft) {
    const feedback = getPhotoQualityFeedback(draft.photo ?? null)
    const failed = feedback?.level === 'fail'
    return (
      <View className='camera-page camera-review'>
        <View className='camera-review__preview'>
          <Image className='camera-review__image' src={draft.path} mode='aspectFit' ariaLabel='待确认的照片' />
        </View>
        <View className='camera-review__panel'>
          {failed ? (
            <View className='camera-review__feedback'>
              <Text className='camera-review__title'>这张照片可能不符合要求</Text>
              {feedback.messages.length > 0
                ? feedback.messages.map((message, index) => <Text key={index}>{message}</Text>)
                : <Text>请正对镜头，在光线均匀的地方重拍。</Text>}
            </View>
          ) : null}
          <View className='camera-review__actions'>
            <Button
              className={`btn-native${failed ? '' : ' btn-native--plain'}`}
              disabled={busy}
              onClick={() => {
                setAlbumOnly(false)
                setDraft(null)
              }}
            >
              重拍
            </Button>
            <Button
              className={`btn-native${failed ? ' btn-native--plain' : ''}`}
              disabled={busy}
              loading={busy}
              onClick={() => void usePhoto(draft, failed)}
            >
              {failed ? '仍然使用' : '用这张'}
            </Button>
          </View>
        </View>
      </View>
    )
  }

  if (!live) {
    const loading = weapp && !albumOnly && cameraState === 'loading'
    const denied = weapp && !albumOnly && cameraState === 'denied'
    return (
      <View className='camera-page camera-unavailable'>
        <View className='camera-unavailable__panel'>
          {albumOnly ? null : (
            <>
              <Text className='camera-unavailable__title'>
                {loading ? '正在打开相机' : denied ? '需要相机权限' : '暂时无法打开相机'}
              </Text>
              {denied ? <Text className='hint'>在微信小程序设置中允许使用相机，就可以拍证件照。</Text> : null}
            </>
          )}
          {denied ? (
            <Button className='btn-native' disabled={busy} onClick={() => void openCameraSettings()}>去设置打开</Button>
          ) : null}
          {weapp && !albumOnly && cameraState === 'unavailable' ? (
            <Button className='btn-native' onClick={() => void requestPermission()}>重试</Button>
          ) : null}
          <Button
            className={`btn-native${albumOnly ? '' : ' btn-native--plain'}`}
            disabled={busy}
            onClick={() => void openAlbum()}
          >
            从相册选
          </Button>
        </View>
      </View>
    )
  }

  const controlsDisabled = busy || countdown > 0
  return (
    <View className='camera-page camera-live'>
      {showFeed ? (
        <Camera
          key={devicePosition}
          className='camera-live__feed'
          devicePosition={devicePosition}
          frameSize='small'
          flash={devicePosition === 'back' && fillLight ? 'on' : 'off'}
          onInitDone={() => setReady(true)}
          onStop={stopCamera}
          onError={() => void onCameraError()}
        />
      ) : null}
      <View className='camera-live__layout'>
        <View className='camera-live__toolbar'>
          <Button
            className='camera-live__control'
            disabled={!ready || controlsDisabled}
            onClick={() => {
              stopLiveGuide()
              setReady(false)
              setDevicePosition(devicePosition === 'front' ? 'back' : 'front')
            }}
          >
            {devicePosition === 'front' ? '切换后置' : '切换前置'}
          </Button>
          <Button
            className='camera-live__control'
            disabled={controlsDisabled}
            onClick={() => setTimerEnabled(!timerEnabled)}
          >
            倒计时 {timerEnabled ? '3 秒' : '关'}
          </Button>
          <Button
            className='camera-live__control'
            disabled={controlsDisabled}
            onClick={() => setFillLight(!fillLight)}
          >
            补光 {fillLight ? '开' : '关'}
          </Button>
          <Button
            className='camera-live__control'
            disabled={controlsDisabled}
            onClick={toggleAutoCapture}
          >
            自动拍 {autoEnabled ? '开' : '关'}
          </Button>
        </View>
        <View className='camera-live__center'>
          <View className='camera-live__hint-slot'>
            <Text className='camera-live__hint'>
              {ready ? (guideHint ? GUIDE_HINT[guideHint] : '手机举到眼睛高度，把脸和肩膀都放进框里') : '正在打开相机'}
            </Text>
          </View>
          <View className='camera-live__target'>
            <View className={`camera-target${frontFill ? ' camera-target--lit' : ''}${guideHint === 'good' ? ' camera-target--good' : ''}`}>
              <View className='camera-target__head' />
              <View className='camera-target__shoulders' />
              <View className='camera-target__line camera-target__line--top'><Text>头顶线</Text></View>
              <View className='camera-target__line camera-target__line--chin'><Text>下巴线</Text></View>
            </View>
          </View>
        </View>
        <View className='camera-live__bottom'>
          <Button className='camera-live__control camera-live__album' disabled={controlsDisabled} onClick={() => void openAlbum()}>
            相册
          </Button>
          <Button className='camera-live__shutter' disabled={!ready || busy} ariaLabel='拍照' onClick={startCapture} />
        </View>
      </View>
      {countdown > 0 ? (
        <View className='camera-countdown'>
          <Text className='camera-countdown__number'>{countdown}</Text>
          <Button className='camera-live__control' onClick={cancelCountdown}>取消</Button>
        </View>
      ) : null}
    </View>
  )
}
