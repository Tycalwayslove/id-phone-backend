import { Text } from '@tarojs/components'
import { fenToYuan } from '../../utils/format'
import './index.scss'

interface Props {
  /** 金额，单位：分 */
  fen: number
  /** 字号档位，默认 normal */
  size?: 'small' | 'normal' | 'large'
}

/** 金额展示：分转元，如 1990 → ¥19.9 */
export default function PriceText({ fen, size = 'normal' }: Props) {
  return (
    <Text className={`price-text price-text--${size}`}>
      <Text className='price-text__sym'>¥</Text>
      {fenToYuan(fen)}
    </Text>
  )
}
