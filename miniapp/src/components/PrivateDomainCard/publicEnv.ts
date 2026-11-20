/** Taro 仅替换已配置的完整变量名。小程序运行时可能没有 process。 */
export function readPublicEnv(read: () => unknown): string {
  try {
    const value = read()
    return typeof value === 'string' ? value.trim() : ''
  } catch {
    return ''
  }
}
