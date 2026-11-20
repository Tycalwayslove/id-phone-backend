import type { components } from '../api/schema'

type Photo = components['schemas']['PhotoOut'] | components['schemas']['PhotoDetail']

/** 兼容 T024 上线前的响应和未做快速检测的旧照片。 */
export function getPhotoQualityFeedback(photo: Photo | null) {
  const quality = photo && 'quality' in photo ? photo.quality : null
  if (!quality || typeof quality !== 'object' || !('level' in quality)) return null
  const { level } = quality
  if (level !== 'fail' && level !== 'warn') return null

  const issues: unknown[] = 'issues' in quality && Array.isArray(quality.issues) ? quality.issues : []
  const messages: string[] = []
  for (const issue of issues) {
    if (!issue || typeof issue !== 'object' || !('message' in issue) || typeof issue.message !== 'string') continue
    const message = issue.message.trim()
    if (message) messages.push(message)
  }
  return { level, messages }
}
