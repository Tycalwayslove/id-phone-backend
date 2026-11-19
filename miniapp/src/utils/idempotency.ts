/** 生成 UUID v4（小程序没有 crypto.randomUUID，用 Math.random 即可，幂等键不需要密码学强度） */
export function newIdempotencyKey(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16)
    const v = c === 'x' ? r : (r % 4) + 8
    return v.toString(16)
  })
}

/**
 * 幂等键保管：同一个操作（fingerprint 相同）重复点击用同一个 key；
 * 操作内容变了换新 key；成功后或明确失败后调用 release() 换新 key。
 */
export function createKeyKeeper(): {
  get: (fingerprint: string) => string
  release: () => void
} {
  let fp = ''
  let key = ''
  return {
    get(fingerprint: string): string {
      if (!key || fp !== fingerprint) {
        fp = fingerprint
        key = newIdempotencyKey()
      }
      return key
    },
    release(): void {
      key = ''
      fp = ''
    }
  }
}
