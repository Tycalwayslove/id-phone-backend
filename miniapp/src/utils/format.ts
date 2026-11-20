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

/** 把规格的十六进制底色归为白、蓝、红，其余颜色保留为“其他”。 */
export function bgColorName(hex: string): '白' | '蓝' | '红' | '其他' {
  const color = hex.trim().replace(/^#/, '')
  const rgb = /^[0-9a-f]{3}$/i.test(color) ? color.replace(/./g, (digit) => digit + digit) : color
  if (!/^[0-9a-f]{6}$/i.test(rgb)) return '其他'
  const value = Number.parseInt(rgb, 16)
  const red = value >> 16
  const green = (value >> 8) & 255
  const blue = value & 255
  if (red === 255 && green === 255 && blue === 255) return '白'
  if (blue - red >= 24 && blue > green) return '蓝'
  if (red - Math.max(green, blue) >= 24 && Math.abs(green - blue) <= (red - Math.min(green, blue)) / 2) return '红'
  return '其他'
}
