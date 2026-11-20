import { useEffect, useRef } from 'react'
import Taro, { useDidHide, useUnload } from '@tarojs/taro'

export default function useFrontFillLight(enabled: boolean): void {
  const original = useRef<number>()
  const queue = useRef(Promise.resolve())
  const restore = useRef<() => void>()

  useDidHide(() => restore.current?.())
  useUnload(() => restore.current?.())

  useEffect(() => {
    if (!enabled) return
    let active = true

    // 串行修改亮度，避免切换摄像头或离页时，尚未完成的提亮覆盖恢复操作。
    queue.current = queue.current.then(async () => {
      if (!active) return
      if (original.current === undefined) {
        const { value } = await Taro.getScreenBrightness()
        if (!active) return
        original.current = value
      }
      await Taro.setScreenBrightness({ value: 1 })
    }).catch(() => {
      if (active) void Taro.showToast({ title: '暂时无法调高屏幕亮度', icon: 'none' })
    })

    function stop(): void {
      active = false
      queue.current = queue.current.then(async () => {
        if (original.current === undefined) return
        await Taro.setScreenBrightness({ value: original.current })
        original.current = undefined
      }).catch(() => undefined)
    }

    restore.current = stop
    return stop
  }, [enabled])
}
