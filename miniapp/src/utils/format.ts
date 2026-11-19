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
