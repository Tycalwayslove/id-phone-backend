/** 金额：分 → 元字符串，1990 → "19.9"，9900 → "99" */
export function fenToYuan(fen: number): string {
  return String(Number((fen / 100).toFixed(2)))
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function parse(iso: string): Date | null {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 日期：2026-11-19（本地时区），无法解析返回空串 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = parse(iso)
  if (!d) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 日期时间：2026-11-19 16:30 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = parse(iso)
  if (!d) return ''
  return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 毫米尺寸文案，如 "25×35mm"；官方未规定时返回空串 */
export function formatMm(w: number | null | undefined, h: number | null | undefined): string {
  return w && h ? `${w}×${h}mm` : ''
}

/** 文件大小范围文案，如 "20-100KB"，无要求返回空串 */
export function formatSizeRange(min: number | null | undefined, max: number | null | undefined): string {
  if (min && max) return `${min}-${max}KB`
  if (max) return `不超过${max}KB`
  if (min) return `不小于${min}KB`
  return ''
}

// 与后端服务商目录的英文底色映射一致。
const LEGACY_BG_COLORS = new Map([
  ['white', '#FFFFFF'],
  ['blue', '#438EDB'],
  ['red', '#FF0000'],
  ['dark_blue', '#1A3B8C'],
  ['grey', '#BFBFBF'],
  ['tint', '#EAF1FB'],
  ['gradient', '#438EDB'],
  ['sky_blue', '#87CEEB'],
  ['gray', '#BFBFBF'],
  ['dark_red', '#8B0000'],
])

/** 将英文色名和十六进制简写转为供色块使用的色值。 */
export function bgColorHex(color: string): string {
  const trimmed = color.trim()
  const mapped = LEGACY_BG_COLORS.get(trimmed.toLowerCase())
  if (mapped) return mapped
  const digits = trimmed.replace(/^#/, '').toUpperCase()
  if (/^[0-9A-F]{3}$/.test(digits)) return `#${digits.replace(/./g, (digit) => digit + digit)}`
  return /^[0-9A-F]{6}$/.test(digits) ? `#${digits}` : trimmed
}

export function bgColorName(color: string): '白' | '蓝' | '红' | '其他' {
  const hex = bgColorHex(color)
  if (!/^#[0-9A-F]{6}$/.test(hex)) return '其他'
  const value = Number.parseInt(hex.slice(1), 16)
  const red = value >> 16
  const green = (value >> 8) & 255
  const blue = value & 255
  if (red === 255 && green === 255 && blue === 255) return '白'
  if (blue - red >= 24 && blue > green) return '蓝'
  if (red - Math.max(green, blue) >= 24 && Math.abs(green - blue) <= (red - Math.min(green, blue)) / 2) return '红'
  return '其他'
}
