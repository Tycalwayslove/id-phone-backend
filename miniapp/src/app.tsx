import type { PropsWithChildren } from 'react'
import '@nutui/nutui-react-taro/dist/style.css'
import './app.scss'
// 导入 store 以注册会话监听（401 静默登录后同步令牌到状态）
import './stores/user'

function App({ children }: PropsWithChildren) {
  return <>{children}</>
}

export default App
