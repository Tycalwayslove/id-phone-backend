import { useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { handleError } from '../utils/errors'
import { PAGES, navigate } from '../utils/nav'

export const SKIP_GUIDE_KEY = 'shoot-guide.skip'

export default function useShootFlow() {
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)

  async function open(code?: string): Promise<void> {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    try {
      const skipGuide = Taro.getStorageSync(SKIP_GUIDE_KEY) === true
      await navigate(skipGuide ? PAGES.camera : PAGES.shootGuide, { spec_code: code })
    } catch (e) {
      await handleError(e)
    } finally {
      locked.current = false
      setBusy(false)
    }
  }

  return { busy, open }
}
