// 参考 shell 前端 utils/auth.js：localStorage 保存登录态，token 为 HMAC 签名的
// JWT 兼容格式（header.payload.signature），每个 API 请求以 Bearer 头携带。
const TOKEN_KEY = 'agentree_token'
const USER_KEY = 'agentree_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user || {}))
}

/**
 * 只替换 token（静默续期时后端下发新 ticket），保留已有的用户信息。
 * 传空值时什么都不做，避免把有效凭证擦掉。
 */
export function setToken(token) {
  if (!token) return
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

/**
 * 解出 JWT payload 用于本地判断有效期。
 *
 * 只做 base64 解码，不验签——浏览器里没有也不该有签名密钥，真实性始终由
 * 服务端把关。这里仅用于"提前知道要不要重新登录"这种体验优化。
 */
export function getTokenPayload() {
  const token = getToken()
  if (!token || token.split('.').length !== 3) return null
  try {
    const seg = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(decodeURIComponent(escape(atob(seg))))
  } catch {
    return null
  }
}

/**
 * token 的过期时间戳（毫秒）；无 exp 声明时返回 0。
 */
export function getExpiresAt() {
  const exp = getTokenPayload()?.exp
  return exp ? Number(exp) * 1000 : 0
}

export function isAuthed() {
  if (!getToken()) return false
  const expiresAt = getExpiresAt()
  // 没有 exp 的 token 交给服务端判断，本地不误伤。
  if (!expiresAt) return true
  // 留 5s 余量容忍客户端与服务端的时钟偏差，避免临界点反复误踢。
  return expiresAt > Date.now() + 5000
}
