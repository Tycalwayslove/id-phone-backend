import { useEffect, useState } from 'react'
import { Input, Text, View } from '@tarojs/components'
import './index.scss'

interface Props {
  placeholder?: string
  /** 初始关键字 */
  value?: string
  /** 点键盘“搜索”时触发 */
  onSearch: (keyword: string) => void
}

/** 搜索框（Taro Input，confirmType=search） */
export default function SearchBox({ placeholder = '搜索规格，如 身份证', value = '', onSearch }: Props) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  return (
    <View className='search-box'>
      <Text className='search-box__icon'>🔍</Text>
      <Input
        className='search-box__input'
        value={text}
        placeholder={placeholder}
        confirmType='search'
        maxlength={50}
        onInput={(e) => setText(e.detail.value)}
        onConfirm={(e) => onSearch(e.detail.value.trim())}
      />
    </View>
  )
}
