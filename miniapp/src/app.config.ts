export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/photos/index',
    'pages/me/index',
    'pages/specs/index',
    'pages/spec-detail/index',
    'pages/editor/index',
    'pages/plans/index',
    'pages/receipt-apply/index',
    'pages/receipts/index',
    'pages/receipt-detail/index',
    'pages/photo-detail/index',
    'pages/orders/index',
    'pages/entitlements/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: '智拍证件照',
    navigationBarTextStyle: 'black',
    backgroundColor: '#F5F6F8'
  },
  // 暂不配图标，只用文字
  tabBar: {
    color: '#646A73',
    selectedColor: '#2B6BFF',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      { pagePath: 'pages/index/index', text: '首页' },
      { pagePath: 'pages/photos/index', text: '证件照' },
      { pagePath: 'pages/me/index', text: '我的' }
    ]
  }
})
