import { App, Form, InputNumber, type FormItemProps } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { errorText } from '../api/client'

export const codeRule = { pattern: /^[a-z0-9_]{2,64}$/, message: '请输入 2～64 位小写字母、数字或下划线' }

export function IntegerField({ name, label, min, max, required = false }: {
  name: string; label: string; min: number; max?: number; required?: boolean
}) {
  return (
    <Form.Item
      name={name} label={label}
      rules={[
        { required, message: `请输入${label}` },
        { type: 'integer', min, max, message: max === undefined ? `请输入不小于 ${min} 的整数` : `请输入 ${min}～${max} 之间的整数` },
      ] satisfies FormItemProps['rules']}
    >
      <InputNumber min={min} max={max} step={1} />
    </Form.Item>
  )
}

/** 只提交编辑过的字段，保留接口对省略字段以及显式 null 的区别。 */
export function changedFields<T extends object>(before: T, after: T) {
  const patch: Partial<T> = {}
  for (const key of Object.keys(after) as (keyof T)[]) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) patch[key] = after[key]
  }
  return patch
}

export function useEditorSave(resource: string, onClose: () => void) {
  const cache = useQueryClient()
  const { message } = App.useApp()
  const savingRef = useRef(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function save(write: () => Promise<unknown>) {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true)
    setError('')
    try {
      await write()
      void cache.invalidateQueries({ queryKey: [resource] })
      void cache.invalidateQueries({ queryKey: ['audit'] })
      void message.success('已保存')
      onClose()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return { saving, error, save, close: () => { if (!savingRef.current) onClose() } }
}
