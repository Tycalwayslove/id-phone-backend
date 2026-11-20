export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

export interface Point {
  x: number
  y: number
}

export interface Frame {
  data: ArrayBuffer
  width: number
  height: number
}

export interface Face {
  box: Rect
  /** 拿不到可靠角度时为空，跳过正脸判断，其余照常 */
  pose?: { pitch: number; yaw: number; roll: number }
  eyes?: readonly (readonly Point[])[]
}

export type Detection = { count: 0 } | { count: 1; face: Face } | { count: 'multiple' }

export interface GuideArea {
  preview: Rect
  target: Rect
  head: Rect
}

export const GUIDE_LIMITS = {
  frameInterval: 220, // 最多约 4.5 帧/秒，每次只处理一帧
  frameTimeout: 3000,
  hintDelay: 500,
  autoDelay: 1000,
  maxSampleAge: 750, // 视频断流时，禁止用旧结果完成自动拍摄
  minWidth: 0.36,
  maxWidth: 0.66, // 外框铺满屏宽，头部轮廓约为外框的 57%；脸宽在外框的 36%~66% 之间都算合适，留出自拍晃动余量
  centerX: 0.13, // 相对于外框宽度、头部轮廓高度的容差
  centerY: 0.16,
  poseDegrees: 10,
  eyeRatio: 0.18, // 上下眼睑间距约小于眼宽的五分之一
  dark: 55,
  bright: 220,
  uneven: 38, // 8 位亮度尺度，只提示明显的曝光和两侧亮度差
  lightSamples: 12
} as const

export const GUIDE_HINT = {
  noFace: '把脸放进框里',
  multiple: '画面里只留你一个人',
  closer: '靠近一点',
  farther: '离远一点',
  moveLeft: '往左移一点',
  moveRight: '往右移一点',
  moveUp: '往上移一点',
  moveDown: '往下移一点',
  turnLeft: '头往左转一点',
  turnRight: '头往右转一点',
  chinDown: '下巴收一点',
  chinUp: '下巴抬一点',
  levelHead: '头摆正',
  openEyes: '请睁开眼睛',
  dark: '光线有点暗，面向窗户或打开补光',
  bright: '光线太强，换个位置',
  leftDark: '左边脸偏暗，转向光源',
  rightDark: '右边脸偏暗，转向光源',
  good: '很好，保持不动'
} as const

export type GuideHint = keyof typeof GUIDE_HINT

export interface GuideStability {
  candidate: GuideHint
  since: number
  observedAt: number
  shown: GuideHint | null
}

export function stabilizeGuide(previous: GuideStability | null, hint: GuideHint, at: number): GuideStability {
  if (!previous || previous.candidate !== hint || at - previous.observedAt > GUIDE_LIMITS.maxSampleAge) {
    return { candidate: hint, since: at, observedAt: at, shown: previous?.shown ?? null }
  }
  const shown = at - previous.since >= GUIDE_LIMITS.hintDelay ? hint : previous.shown
  return { ...previous, observedAt: at, shown }
}

function projectBox(box: Rect, frame: Frame, preview: Rect, mirrored: boolean): Rect {
  // 取景画面按等比铺满计算，原始帧超出取景区域的部分从中心裁掉。
  const scale = Math.max(preview.width / frame.width, preview.height / frame.height)
  const offsetX = preview.left + (preview.width - frame.width * scale) / 2
  const offsetY = preview.top + (preview.height - frame.height * scale) / 2
  const left = mirrored ? frame.width - box.left - box.width : box.left
  return { left: offsetX + left * scale, top: offsetY + box.top * scale, width: box.width * scale, height: box.height * scale }
}

/** 六点从眼角沿眼睑排列，对侧眼角为第 4 个点。 */
export function eyeAspectRatio(points: readonly Point[]): number | undefined {
  if (points.length !== 6 || points.some(({ x, y }) => !Number.isFinite(x) || !Number.isFinite(y))) return
  const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y)
  const width = distance(points[0], points[3])
  if (width < 1) return
  return (distance(points[1], points[5]) + distance(points[2], points[4])) / (2 * width)
}

export function sampleFaceLighting(frame: Frame, face: Rect): { left: number; right: number } | undefined {
  const pixels = new Uint8Array(frame.data)
  if (pixels.length !== frame.width * frame.height * 4) return
  const samples = GUIDE_LIMITS.lightSamples
  const totals = [0, 0]
  const counts = [0, 0]
  for (let row = 0; row < samples; row++) {
    const y = (row + 0.5) / samples - 0.5
    const pixelY = Math.floor(face.top + face.height * (0.52 + y * 0.62))
    if (pixelY < 0 || pixelY >= frame.height) continue
    for (let col = 0; col < samples; col++) {
      const x = (col + 0.5) / samples - 0.5
      // 椭圆内等距采样，尽量避开脸框边缘的背景与头发。
      if (x * x + y * y > 0.25) continue
      const pixelX = Math.floor(face.left + face.width * (0.5 + x * 0.78))
      if (pixelX < 0 || pixelX >= frame.width) continue
      const i = (pixelY * frame.width + pixelX) * 4
      const half = x < 0 ? 0 : 1
      totals[half] += pixels[i] * 0.299 + pixels[i + 1] * 0.587 + pixels[i + 2] * 0.114
      counts[half]++
    }
  }
  if (counts[0] && counts[1]) return { left: totals[0] / counts[0], right: totals[1] / counts[1] }
}

/** 姿态已换算为角度，框和关键点使用原始帧像素坐标。返回 null 表示当前帧无法判定。 */
export function evaluateFaceGuide(detection: Detection, frame: Frame, area: GuideArea, mirrored: boolean): GuideHint | null {
  if (detection.count === 0) return 'noFace'
  if (detection.count === 'multiple') return 'multiple'

  const { box, pose, eyes } = detection.face
  const visibleFace = projectBox(box, frame, area.preview, mirrored)
  const ratio = visibleFace.width / area.target.width
  if (ratio < GUIDE_LIMITS.minWidth) return 'closer'
  if (ratio > GUIDE_LIMITS.maxWidth) return 'farther'

  const { head } = area
  const offsetX = (visibleFace.left + visibleFace.width / 2 - head.left - head.width / 2) / (area.target.width * GUIDE_LIMITS.centerX)
  const offsetY = (visibleFace.top + visibleFace.height / 2 - head.top - head.height / 2) / (head.height * GUIDE_LIMITS.centerY)
  if (Math.abs(offsetX) > 1 && Math.abs(offsetX) >= Math.abs(offsetY)) return offsetX > 0 ? 'moveLeft' : 'moveRight'
  if (Math.abs(offsetY) > 1) return offsetY > 0 ? 'moveUp' : 'moveDown'

  // 正偏航表示脸朝原始画面右边，正俯仰表示下巴抬起。
  if (pose) {
    const yaw = mirrored ? -pose.yaw : pose.yaw
    if (Math.abs(yaw) > GUIDE_LIMITS.poseDegrees) return yaw > 0 ? 'turnLeft' : 'turnRight'
    if (Math.abs(pose.pitch) > GUIDE_LIMITS.poseDegrees) return pose.pitch > 0 ? 'chinDown' : 'chinUp'
    if (Math.abs(pose.roll) > GUIDE_LIMITS.poseDegrees) return 'levelHead'
  }

  if (eyes?.some(eye => (eyeAspectRatio(eye) ?? Infinity) < GUIDE_LIMITS.eyeRatio)) return 'openEyes'

  const light = sampleFaceLighting(frame, box)
  if (!light) return null
  const average = (light.left + light.right) / 2
  if (average < GUIDE_LIMITS.dark) return 'dark'
  if (average > GUIDE_LIMITS.bright) return 'bright'
  const difference = (light.right - light.left) * (mirrored ? -1 : 1)
  if (Math.abs(difference) > GUIDE_LIMITS.uneven) return difference > 0 ? 'leftDark' : 'rightDark'
  return 'good'
}
