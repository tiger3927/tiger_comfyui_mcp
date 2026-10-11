import { defineStore } from 'pinia'

// 双主题：localStorage 持久化 + 跟随系统 prefers-color-scheme（§7.1）
const KEY = 'tiger_portal_theme'

function initTheme() {
  const saved = localStorage.getItem(KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ theme: initTheme() }),
  actions: {
    apply() {
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
    },
    toggle() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem(KEY, this.theme)
      this.apply()
    },
  },
})
