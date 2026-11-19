/** 18 位身份证号格式：17 位数字 + 数字或 X（只做格式校验，真伪由服务端判断） */
export function isIdCard18(v: string): boolean {
  return /^\d{17}[\dXx]$/.test(v)
}
