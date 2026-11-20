export default defineAppConfig({
  __usePrivacyCheck__: true,
  pages: [
    'pages/index/index',
    'pages/photos/index',
    'pages/me/index',
    'pages/specs/index',
    'pages/spec-detail/index',
    'pages/shoot-guide/index',
    'pages/camera/index',
    'pages/editor/index',
    'pages/plans/index',
    'pages/receipt-apply/index',
    'pages/receipts/index',
    'pages/receipt-detail/index',
    'pages/photo-detail/index',
    'pages/orders/index',
    'pages/order-detail/index',
    'pages/entitlements/index',
    'pages/entitlement-detail/index',
    'pages/legal/agreement/index',
    'pages/legal/privacy/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: '智拍证件照',
    navigationBarTextStyle: 'black',
    backgroundColor: '#EEF1F5'
  },
  // 暂不配图标，只用文字
  tabBar: {
    color: '#5B6577',
    selectedColor: '#2F6CC8',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      { pagePath: 'pages/index/index', text: '首页' },
      { pagePath: 'pages/photos/index', text: '我的照片' },
      { pagePath: 'pages/me/index', text: '我的' }
    ]
  }
})
