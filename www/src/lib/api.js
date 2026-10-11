// Axios 实例：baseURL /portal/api（dev 由 vite proxy 转发到 18503 纯门户后端；
// 生产同域由 main.py 提供）。统一 401 跳登录、错误体 {error:{code,message}} 解析（§6、§7）。
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, setToken } from './auth'
import router from '../router'

const api = axios.create({ baseURL: '/portal/api', timeout: 20000 })

api.interceptors.request.use((cfg) => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const data = err.response?.data
    const msg =
      (data && data.error && (data.error.message || data.error.code)) ||
      (data && data.detail) ||
      err.message ||
      '请求失败'
    if (err.response?.status === 401) {
      setToken(null)
      if (router.currentRoute.value.name !== 'login') {
        router.push({ name: 'login' })
      }
      ElMessage.error(msg)
    } else if (err.response) {
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  },
)

export default api
