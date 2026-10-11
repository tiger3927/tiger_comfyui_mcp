import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base=/portal/ 与生产一致：main.py 用 StaticFiles(html=True) 把 dist 挂在 /portal/ 下。
// 开发期：vite dev 起 127.0.0.1:5173，/portal/api 代理到本机 scripts/dev_portal.py
// 起的纯门户后端 18503（只 import portal，无 ComfyUI，纯本地可推进 M3）。
export default defineConfig({
  base: '/portal/',
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/portal/api': {
        target: 'http://127.0.0.1:18503',
        changeOrigin: true,
      },
    },
  },
})
