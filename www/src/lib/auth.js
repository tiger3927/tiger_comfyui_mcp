// 门户 JWT 存取（独立于 mcp Bearer，§6）
const KEY = 'tiger_portal_token'

export function getToken() {
  return localStorage.getItem(KEY) || ''
}
export function setToken(t) {
  if (t) localStorage.setItem(KEY, t)
  else localStorage.removeItem(KEY)
}
