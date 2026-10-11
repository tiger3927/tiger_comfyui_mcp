import { defineStore } from 'pinia'
import api from '../lib/api'
import { getToken, setToken } from '../lib/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getToken(),
    user: null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    role: (s) => s.user?.role || '',
    isAdmin: (s) => s.user?.role === 'admin',
    username: (s) => s.user?.username || '',
  },
  actions: {
    async login(username, password, captchaId, captchaCode) {
      const data = await api.post('/auth/login', {
        username, password, captcha_id: captchaId, captcha_code: captchaCode,
      })
      this.token = data.token
      this.user = data.user
      setToken(data.token)
      return data.user
    },
    async register(username, password, captchaId, captchaCode) {
      const data = await api.post('/auth/register', {
        username, password, captcha_id: captchaId, captcha_code: captchaCode,
      })
      this.token = data.token
      this.user = data.user
      setToken(data.token)
      return data.user
    },
    async fetchMe() {
      this.user = await api.get('/me')
      return this.user
    },
    logout() {
      this.token = ''
      this.user = null
      setToken(null)
    },
  },
})
