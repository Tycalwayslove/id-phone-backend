/// <reference types="@tarojs/taro" />

declare module '*.png'
declare module '*.gif'
declare module '*.jpg'
declare module '*.jpeg'
declare module '*.svg'
declare module '*.css'
declare module '*.less'
declare module '*.scss'
declare module '*.sass'
declare module '*.styl'

declare namespace NodeJS {
  interface ProcessEnv {
    /** 后端地址，来自 .env.* */
    TARO_APP_API_BASE?: string
    /** 是否开启 fake 支付/模拟结果，"1" 为开启 */
    TARO_APP_FAKE_PAY?: string
  }
}
