import type Taro from '@tarojs/taro'
import { evaluateFaceGuide, GUIDE_LIMITS, type Detection, type Frame, type GuideArea, type GuideHint, type Point, type Rect } from './faceGuide'

type AnchorCallback = (anchors: unknown) => void
type ImageInput = { frameBuffer: ArrayBuffer; width: number; height: number }
type Callbacks<T = unknown> = { success: (result: T) => void; fail: (error: unknown) => void }

interface VisionSession {
  start(callback: (error?: unknown) => void): void
  on(event: 'updateAnchors', callback: AnchorCallback): void
  off?(event: 'updateAnchors', callback: AnchorCallback): void
  destroy(): void
  detectFace(input: ImageInput & { sourceType: 0 }): void
}

// Taro 的 createVKSession 类型未声明 face 配置，原生接口按 miniprogram-api-typings 3.12.3 调用。
// 两套类型对部分响应字段的声明不一致，因此使用 unknown 读取回调数据。
interface WechatFaceApi {
  isVKSupport?(version: 'v1'): boolean
  createVKSession?(config: { version: 'v1'; track: { face: { mode: 2 } } }): VisionSession
  initFaceDetect?(callbacks: Callbacks): void
  stopFaceDetect?(): void
  faceDetect?(input: ImageInput & Callbacks & { enableMultiFace: true; enablePoint: true; enableAngle: true }): void
}

declare const wx: WechatFaceApi | undefined

interface Detector {
  start(): Promise<void>
  detect(frame: Frame): Promise<Detection>
  stop(): void
}

const LEGACY_DEGREES_PER_UNIT = 90 // 类型只注明 [-1, 1]，暂按 ±90° 线性估计
const LEGACY_ANGLE_LIMIT = 1
const VISION_DEGREES_PER_RADIAN = 180 / Math.PI // 暂按 [pitch, yaw, roll] 弧度读取
const EYE_CONTOURS = [[35, 41, 42, 39, 37, 36], [89, 95, 96, 93, 91, 90]] as const

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function readBox(x: unknown, y: unknown, width: unknown, height: unknown, frame: Frame, normalized: boolean): Rect | undefined {
  if (!finite(x) || !finite(y) || !finite(width) || !finite(height) || width <= 0 || height <= 0) return
  const sx = normalized ? frame.width : 1
  const sy = normalized ? frame.height : 1
  const box = { left: x * sx, top: y * sy, width: width * sx, height: height * sy }
  if (box.width > frame.width || box.height > frame.height || box.left >= frame.width || box.top >= frame.height ||
    box.left + box.width <= 0 || box.top + box.height <= 0) return
  return box
}

/** 角度单位以真机为准：数值落在 limit 内按 degreesPerUnit 换算，超出则视为已经是“度”；超过 180 视为无效 */
function readPose(pitch: unknown, yaw: unknown, roll: unknown, limit: number, degreesPerUnit: number) {
  if (!finite(pitch) || !finite(yaw) || !finite(roll)) return
  const max = Math.max(Math.abs(pitch), Math.abs(yaw), Math.abs(roll))
  if (max > 180) return
  const scale = max <= limit ? degreesPerUnit : 1
  return { pitch: pitch * scale, yaw: yaw * scale, roll: roll * scale }
}

function readEyes(raw: unknown, box: Rect, frame: Frame): Point[][] | undefined {
  if (!Array.isArray(raw) || raw.length !== 106) return
  const contours = EYE_CONTOURS.map(indices => indices.map(index => record(raw[index])))
  const points = contours.map(contour => contour.flatMap(({ x, y }) => finite(x) && finite(y) ? [{ x, y }] : []))
  if (points.some(eye => eye.length !== 6)) return

  // 类型未标明编号。只在候选轮廓符合双眼位置和眼角排布时计算，其他布局跳过。
  const normalized = points.every(eye => eye.every(({ x, y }) => Math.abs(x) <= 1 && Math.abs(y) <= 1))
  const eyes = points.map(eye => eye.map(({ x, y }) => ({
    x: (normalized ? x * frame.width : x) - box.left,
    y: (normalized ? y * frame.height : y) - box.top
  })))
  const centers: Point[] = []
  for (const eye of eyes) {
    const [corner, lidA, lidB, opposite, otherLidB, otherLidA] = eye
    const width = Math.abs(opposite.x - corner.x)
    const left = Math.min(corner.x, opposite.x)
    const right = Math.max(corner.x, opposite.x)
    const centerX = (left + right) / 2 / box.width
    const centerY = (corner.y + opposite.y) / 2 / box.height
    const gapA = otherLidA.y - lidA.y
    const gapB = otherLidB.y - lidB.y
    if (width < box.width * 0.09 || width > box.width * 0.36 || centerY < 0.15 || centerY > 0.65 ||
      left < 0 || right > box.width ||
      [lidA, lidB, otherLidA, otherLidB].some(point => point.x < left || point.x > right) ||
      (gapA > 1 && gapB < -1) || (gapA < -1 && gapB > 1)) return
    centers.push({ x: centerX, y: centerY })
  }
  const [first, second] = centers
  if ((first.x - 0.5) * (second.x - 0.5) >= 0 || Math.abs(first.y - second.y) > 0.15) return
  return eyes
}

/** 第一次拿到结果时打印原始数据的结构，便于真机核对字段和单位 */
const loggedSamples = new Set<string>()

function logFirstSample(name: string, raw: unknown): void {
  if (loggedSamples.has(name)) return
  loggedSamples.add(name)
  try {
    const sample = Array.isArray(raw) ? raw[0] : raw
    const r = record(sample)
    const summary = Object.fromEntries(Object.entries(r).map(([k, v]) => [
      k, Array.isArray(v) ? `数组(${v.length})${v.length <= 4 ? ' ' + JSON.stringify(v) : ''}` : typeof v === 'object' ? JSON.stringify(v) : v
    ]))
    console.info(`[实时检测] ${name} 首帧原始数据`, summary)
  } catch {
    // 只用于诊断
  }
}

function visionResult(value: unknown, frame: Frame): Detection {
  logFirstSample('VisionKit', Array.isArray(value) ? value.find(a => record(a).type === 3) ?? value : value)
  if (!Array.isArray(value)) throw new Error('VisionKit anchors unavailable')
  const faces = value.map(record).filter(anchor => anchor.type === 3)
  if (value.length && !faces.length) throw new Error('VisionKit face anchors unavailable')
  if (!faces.length) return { count: 0 }
  if (faces.length > 1) return { count: 'multiple' }

  const { origin, size, points, angle } = faces[0]
  const { x, y } = record(origin)
  const { width, height } = record(size)
  const box = readBox(x, y, width, height, frame, true)
  const pose = Array.isArray(angle) && angle.length === 3
    ? readPose(angle[0], angle[1], angle[2], Math.PI, VISION_DEGREES_PER_RADIAN)
    : undefined
  if (!box) throw new Error('VisionKit face box unavailable')
  return { count: 1, face: { box, pose, eyes: readEyes(points, box, frame) } }
}

function legacyResult(value: unknown, frame: Frame): Detection {
  logFirstSample('faceDetect', value)
  const result = record(value)
  const { faceInfo } = result
  if (Array.isArray(faceInfo) && faceInfo.length > 1) return { count: 'multiple' }
  const face = Array.isArray(faceInfo) && faceInfo.length ? record(faceInfo[0]) : result
  if (face.x === -1 || face.y === -1) return { count: 0 }

  const { originX, originY, width, weight, height } = record(face.detectRect)
  const faceWidth = width ?? weight
  const normalized = [originX, originY, faceWidth, height].every(n => finite(n) && Math.abs(n) <= 1)
  const box = readBox(originX, originY, faceWidth, height, frame, normalized)
  const angle = Array.isArray(face.angleArray) ? face.angleArray[0] : face.angleArray
  const { pitch, yaw, roll } = record(angle)
  const pose = readPose(pitch, yaw, roll, LEGACY_ANGLE_LIMIT, LEGACY_DEGREES_PER_UNIT)
  if (Array.isArray(faceInfo) && !faceInfo.length && !box) return { count: 0 }
  if (!box) throw new Error('FaceDetect face box unavailable')
  return { count: 1, face: { box, pose, eyes: readEyes(face.pointArray, box, frame) } }
}

function nativeInput({ data, width, height }: Frame): ImageInput {
  return { frameBuffer: data, width, height }
}

function ignoreStopError(stop: () => void): void {
  try {
    stop()
  } catch {
    // 相机组件在离页或切换摄像头时可能已经被平台回收。
  }
}

function createVisionDetector(api: WechatFaceApi): Detector | undefined {
  if (api.isVKSupport?.('v1') === false) return
  // 静态图检测模式可输入 Camera 帧，避免第二个会话抢占取景摄像头。
  const session = api.createVKSession?.({ version: 'v1', track: { face: { mode: 2 } } })
  if (!session) return
  if (typeof session.detectFace !== 'function' || typeof session.destroy !== 'function' ||
    typeof session.start !== 'function' || typeof session.on !== 'function') {
    ignoreStopError(() => session.destroy?.())
    return
  }

  let pending: AnchorCallback | undefined
  const onAnchors: AnchorCallback = anchors => {
    const receive = pending
    pending = undefined
    receive?.(anchors)
  }
  return {
    start: () => new Promise((resolve, reject) => {
      session.on('updateAnchors', onAnchors)
      session.start(error => error ? reject(error) : resolve())
    }),
    detect: async frame => {
      const anchors = await new Promise(resolve => {
        pending = resolve
        session.detectFace({ ...nativeInput(frame), sourceType: 0 })
      })
      return visionResult(anchors, frame)
    },
    stop: () => {
      pending = undefined
      ignoreStopError(() => session.off?.('updateAnchors', onAnchors))
      session.destroy()
    }
  }
}

let legacyOwner: symbol | undefined

function createLegacyDetector(api: WechatFaceApi): Detector | undefined {
  const { initFaceDetect, faceDetect, stopFaceDetect } = api
  if (typeof initFaceDetect !== 'function' || typeof faceDetect !== 'function' || typeof stopFaceDetect !== 'function') return
  const owner = Symbol()
  let stopped = false
  return {
    start: () => new Promise((resolve, reject) => {
      legacyOwner = owner
      initFaceDetect.call(api, {
        success: () => {
          // 初始化可能在超时或页面退出后才返回，不能关闭后来启动的检测。
          if (stopped && !legacyOwner) ignoreStopError(() => stopFaceDetect.call(api))
          resolve()
        },
        fail: reject
      })
    }),
    detect: async frame => {
      const result = await new Promise((success, fail) => {
        faceDetect.call(api, {
          ...nativeInput(frame), enableMultiFace: true, enablePoint: true, enableAngle: true, success, fail
        })
      })
      return legacyResult(result, frame)
    },
    stop: () => {
      stopped = true
      if (legacyOwner !== owner) return
      legacyOwner = undefined
      stopFaceDetect.call(api)
    }
  }
}

/** 实时检测状态：给页面显示用 */
export type GuideStatus = 'starting' | 'running' | 'unavailable'

const NAMES = ['VisionKit', 'faceDetect'] as const
/** 连续这么多帧出错才换下一种检测方式（偶发错误不放弃） */
const MAX_CONSECUTIVE_ERRORS = 5
/** 两种方式都失败后，隔一段时间从头重试 */
const RETRY_AFTER_MS = 5000

/** 输出 null 时暂时没有可靠的实时结果，调用方仍可手动拍摄。 */
export function startFaceGuide(
  context: Taro.CameraContext,
  area: GuideArea,
  mirrored: boolean,
  onSample: (hint: GuideHint | null, at: number) => void,
  onStatus: (status: GuideStatus) => void = () => {}
): () => void {
  const api = typeof wx === 'undefined' ? undefined : wx
  if (!api || typeof context.onCameraFrame !== 'function') {
    console.warn('[实时检测] 当前环境不支持相机帧或人脸接口，只能手动拍摄')
    onStatus('unavailable')
    return () => {}
  }

  const factories = [createVisionDetector, createLegacyDetector]
  let stopAttempt: (() => void) | undefined
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  let next = 0

  function attempt(api: WechatFaceApi): void {
    if (disposed) return
    const index = next++
    const factory = factories[index]
    if (!factory) {
      console.warn(`[实时检测] 两种检测方式都不可用，${RETRY_AFTER_MS / 1000} 秒后重试`)
      onStatus('unavailable')
      retryTimer = setTimeout(() => {
        next = 0
        attempt(api)
      }, RETRY_AFTER_MS)
      return
    }
    const name = NAMES[index]
    onStatus('starting')
    let active = true
    let processing = false
    let lastFrame = -Infinity
    let errors = 0
    let detector: Detector | undefined
    let listener: Taro.CameraFrameListener | undefined
    let watchdog = setTimeout(() => fallback('超时没有拿到检测结果'), GUIDE_LIMITS.frameTimeout)

    function stop(): void {
      active = false
      clearTimeout(watchdog)
      ignoreStopError(() => listener?.stop())
      ignoreStopError(() => detector?.stop())
    }

    function fallback(reason: string, error?: unknown): void {
      if (!active) return
      console.warn(`[实时检测] ${name} 停用：${reason}`, error ?? '')
      stop()
      onSample(null, Date.now())
      attempt(api)
    }

    async function onFrame(frame: Frame): Promise<void> {
      const at = Date.now()
      if (!active || !detector || processing || at - lastFrame < GUIDE_LIMITS.frameInterval) return
      if (!frame || !Number.isInteger(frame.width) || !Number.isInteger(frame.height) ||
        frame.width <= 0 || frame.height <= 0 || frame.data?.byteLength !== frame.width * frame.height * 4) return
      lastFrame = at
      processing = true
      try {
        const detection = await detector.detect(frame)
        if (!active) return
        errors = 0
        const hint = evaluateFaceGuide(detection, frame, area, mirrored)
        if (hint !== null) {
          clearTimeout(watchdog)
          watchdog = setTimeout(() => fallback('超时没有拿到检测结果'), GUIDE_LIMITS.frameTimeout)
          onStatus('running')
        }
        onSample(hint, at)
      } catch (e) {
        errors += 1
        if (errors === 1) console.warn(`[实时检测] ${name} 单帧出错（连续 ${MAX_CONSECUTIVE_ERRORS} 次才停用）`, e)
        if (errors >= MAX_CONSECUTIVE_ERRORS) fallback('连续出错', e)
      } finally {
        processing = false
      }
    }

    async function start(): Promise<void> {
      try {
        detector = factory(api)
        if (!detector) return fallback('接口不可用')
        await detector.start()
        if (!active) return
        console.info(`[实时检测] 使用 ${name}`)
        listener = context.onCameraFrame(frame => void onFrame(frame))
        listener.start({ fail: (e: unknown) => fallback('相机帧监听启动失败', e) })
      } catch (e) {
        fallback('启动失败', e)
      }
    }

    stopAttempt = stop
    void start()
  }

  attempt(api)
  return () => {
    disposed = true
    clearTimeout(retryTimer)
    const stop = stopAttempt
    stopAttempt = undefined
    stop?.()
  }
}
