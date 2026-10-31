// 参考 shell 前端 utils/http.js：单一 axios 实例，自动附带 JWT，401 时清登录态
// 并弹回 /login（hash 路由）。agentree 后端无应用层加密，故去掉 bodyCrypto。
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, setToken, clearAuth } from './auth'

const http = axios.create({ timeout: 20000 })

// 防抖：多个请求同时失败（比如后端挂了）时不要刷屏报错。
let lastErrorToast = 0
const ERROR_TOAST_COOLDOWN = 2000

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => {
    // 后端在 token 临期时可通过响应头下发新 ticket，前端跟着响应走。
    const refreshed = resp?.headers?.['x-refreshed-token'] || resp?.headers?.['X-Refreshed-Token']
    if (refreshed) setToken(refreshed)
    return resp
  },
  (error) => {
    const status = error?.response?.status
    const code = error?.response?.data?.code
    if (status === 401 || code === 401) {
      clearAuth()
      if (location.hash.indexOf('/login') === -1) {
        // 带上来源页，重新登录后能跳回原来正在做的事，而不是被丢回首页。
        const from = location.hash.replace(/^#/, '') || '/'
        location.hash = `#/login?redirect=${encodeURIComponent(from)}`
      }
    } else if (status === 403) {
      // 403 = 已认证但无权限 — 不自动跳转。
    } else if (!error?.response) {
      // 无响应 = 网络错误 / 超时 / CORS，后端不可达。
      const now = Date.now()
      if (now - lastErrorToast > ERROR_TOAST_COOLDOWN) {
        lastErrorToast = now
        ElMessage.error('Network request failed: cannot reach the server')
      }
    } else if (status >= 500) {
      const msg = error?.response?.data?.msg
      const now = Date.now()
      if (now - lastErrorToast > ERROR_TOAST_COOLDOWN) {
        lastErrorToast = now
        ElMessage.error(msg || `Server error (${status})`)
      }
    }
    return Promise.reject(error)
  }
)

export default http
