import { App, type ModalFuncProps } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { errorText } from '../api/client'

export function useConfirmChange(resource: string) {
  const { message, modal } = App.useApp()
  const cache = useQueryClient()
  const dialog = useRef<ReturnType<typeof modal.confirm>>()
  useEffect(() => () => dialog.current?.destroy(), [])

  return (options: Pick<ModalFuncProps, 'title' | 'content' | 'okText' | 'okType'>, change: () => Promise<unknown>, success: string) => {
    if (dialog.current) return
    dialog.current = modal.confirm({
      ...options,
      cancelText: '取消',
      maskClosable: false,
      afterClose: () => { dialog.current = undefined },
      async onOk() {
        try {
          await change()
          void message.success(success)
        } catch (error) {
          void message.error(errorText(error))
        } finally {
          void cache.invalidateQueries({ queryKey: [resource] })
          void cache.invalidateQueries({ queryKey: ['audit'] })
        }
      },
    })
  }
}
