import { useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import type { components } from '../api/schema'
import { getSpec } from '../api/specs'
import { handleError, isUserCancel } from '../utils/errors'
import { PAGES, navigate } from '../utils/nav'
import { pickAndCreatePhoto, type PhotoSource } from '../utils/pickPhoto'

type SpecDetail = components['schemas']['SpecDetail']
const SKIP_GUIDE_KEY = 'shoot-guide.skip'

async function createPhoto(source: PhotoSource, specCode?: string): Promise<void> {
  const photo = await pickAndCreatePhoto(source)
  if (photo) await navigate(PAGES.editor, { photo_id: photo.id, spec_code: specCode })
}

export default function useShootFlow() {
  const [guide, setGuide] = useState<{ spec?: SpecDetail } | null>(null)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)

  async function run(action: () => Promise<void>): Promise<void> {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    try {
      await action()
    } catch (e) {
      if (!isUserCancel(e)) await handleError(e)
    } finally {
      locked.current = false
      setBusy(false)
    }
  }

  function open(code?: string, detail?: SpecDetail): Promise<void> {
    return run(async () => {
      if (Taro.getStorageSync(SKIP_GUIDE_KEY) === true) {
        // 系统菜单先区分两个入口，给创建照片接口传入真实来源。
        const { tapIndex } = await Taro.showActionSheet({ itemList: ['拍照', '从相册选'] })
        if (tapIndex === 0 || tapIndex === 1) await createPhoto(tapIndex === 0 ? 'camera' : 'upload', code)
        return
      }
      setGuide({ spec: detail ?? (code ? await getSpec(code) : undefined) })
    })
  }

  function choose(source: PhotoSource, skip: boolean): Promise<void> {
    if (!guide) return Promise.resolve()
    return run(async () => {
      if (skip) Taro.setStorageSync(SKIP_GUIDE_KEY, true)
      setGuide(null)
      await createPhoto(source, guide.spec?.code)
    })
  }

  return { guideOpen: guide !== null, spec: guide?.spec, busy, open, choose, close: () => setGuide(null) }
}
