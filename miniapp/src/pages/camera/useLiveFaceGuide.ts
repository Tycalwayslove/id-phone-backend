import { useEffect, useRef } from 'react'
import Taro, { useDidHide, useUnload } from '@tarojs/taro'
import { startFaceGuide } from '../../utils/faceDetector'
import type { GuideHint, Rect } from '../../utils/faceGuide'

function readRect(node: Partial<Rect> | null | undefined): Rect | undefined {
  if (!node) return
  const { left, top, width, height } = node
  if (typeof left !== 'number' || typeof top !== 'number' || typeof width !== 'number' ||
    typeof height !== 'number' || !(width > 0) || !(height > 0)) return
  return { left, top, width, height }
}

export default function useLiveFaceGuide(
  enabled: boolean,
  mirrored: boolean,
  onSample: (hint: GuideHint | null, at: number) => void
): () => void {
  const receiveSample = useRef(onSample)
  receiveSample.current = onSample
  const dispose = useRef<() => void>()

  function stop(): void {
    dispose.current?.()
  }

  useDidHide(stop)
  useUnload(stop)

  useEffect(() => {
    if (!enabled) return
    let active = true
    let stopDetection: (() => void) | undefined
    function disposeGuide(): void {
      active = false
      stopDetection?.()
      stopDetection = undefined
      if (dispose.current === disposeGuide) dispose.current = undefined
    }
    dispose.current = disposeGuide

    try {
      const query = Taro.createSelectorQuery()
      query.select('.camera-live').boundingClientRect()
      query.select('.camera-target').boundingClientRect()
      query.select('.camera-target__head').boundingClientRect()
      query.exec(nodes => {
        if (!active || !Array.isArray(nodes)) return
        const [previewNode, targetNode, headNode] = nodes
        const preview = readRect(previewNode)
        const target = readRect(targetNode)
        const head = readRect(headNode)
        if (!preview || !target || !head) return
        try {
          stopDetection = startFaceGuide(Taro.createCameraContext(), { preview, target, head }, mirrored,
            (hint, at) => receiveSample.current(hint, at))
        } catch {
          disposeGuide()
        }
      })
    } catch {
      disposeGuide()
    }
    return disposeGuide
  }, [enabled, mirrored])

  return stop
}
