<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../lib/api'
import { useUserStore } from '../store/user'
import { useThemeStore } from '../store/theme'

const router = useRouter()
const route = useRoute()
const user = useUserStore()
const theme = useThemeStore()

const B = import.meta.env.BASE_URL
const mode = ref('login')
const form = ref({ username: '', password: '', password2: '', captchaCode: '' })
const loading = ref(false)
const captcha = ref({ id: '', image: '' })

async function refreshCaptcha() {
  try {
    const data = await api.get('/auth/captcha')
    captcha.value = { id: data.captcha_id, image: data.image }
    form.value.captchaCode = ''
  } catch (e) {
    /* 拦截器已提示 */
  }
}
onMounted(refreshCaptcha)

const isDark = computed({
  get: () => theme.theme === 'dark',
  set: (v) => {
    theme.theme = v ? 'dark' : 'light'
    localStorage.setItem('tiger_portal_theme', theme.theme)
    theme.apply()
  },
})
const heroSrc = computed(() => B + `assets/hero-${theme.theme}.png`)

async function submit() {
  if (mode.value === 'register') {
    if (form.value.username.length < 4) return ElMessage.warning('用户名至少 4 位')
    if (form.value.password.length < 8) return ElMessage.warning('密码至少 8 位')
    if (form.value.password !== form.value.password2) return ElMessage.warning('两次密码不一致')
  }
  if (!form.value.captchaCode) return ElMessage.warning('请输入验证码')
  loading.value = true
  try {
    if (mode.value === 'login') await user.login(form.value.username, form.value.password, captcha.value.id, form.value.captchaCode)
    else await user.register(form.value.username, form.value.password, captcha.value.id, form.value.captchaCode)
    ElMessage.success(mode.value === 'login' ? '登录成功' : '注册成功，余额 0，可充值')
    // 登录分流（§7.2）：管理员进管理后台，普通用户进账户总览（无 redirect 时）
    const target = route.query.redirect || (user.isAdmin ? { name: 'admin-users' } : { name: 'overview' })
    router.push(target)
  } catch (e) {
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card" :body-style="{ padding: '0 0 20px' }">
      <div class="login-hero-wrap">
        <img class="login-hero" :src="heroSrc" alt="hero" @error="e => (e.target.style.display = 'none')" />
        <div class="hero-slogan"><span>AI 视频创作 · 智能体工具链</span></div>
      </div>
      <div class="login-brand">
        <img class="login-logo" :src="B + 'assets/logo.svg'" alt="logo" />
        <h2 class="login-title">老虎C站</h2>
      </div>
      <p class="login-sub">AI 视频创作 · 积分计费 · 任务归属</p>
      <el-form :model="form" class="login-form" @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" clearable />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password" type="password" placeholder="密码" size="large"
            show-password @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item v-if="mode === 'register'">
          <el-input
            v-model="form.password2" type="password" placeholder="确认密码" size="large"
            show-password @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item>
          <div class="captcha-row">
            <el-input
              v-model="form.captchaCode" placeholder="验证码" size="large"
              maxlength="4" @keyup.enter="submit"
            />
            <img v-if="captcha.image" class="captcha-img" :src="captcha.image"
              alt="验证码" title="看不清？点击换一张" @click="refreshCaptcha" />
            <el-button v-else size="large" @click="refreshCaptcha">换一张</el-button>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
            {{ mode === 'login' ? '登 录' : '注 册' }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="switch-line">
        <span class="muted">{{ mode === 'login' ? '还没有账号？' : '已有账号？' }}</span>
        <a href="javascript:;" @click="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? '去注册' : '去登录' }}
        </a>
      </div>
      <div style="text-align: right; margin-top: 10px">
        <el-switch v-model="isDark" inline-prompt active-text="深色" inactive-text="浅色" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-hero-wrap { position: relative; overflow: hidden; border-radius: var(--radius-md) var(--radius-md) 0 0; }
.login-hero {
  width: 100%; height: 190px; object-fit: cover; object-position: center; display: block;
  animation: kenburns 18s ease-in-out infinite alternate;
}
@keyframes kenburns { from { transform: scale(1); } to { transform: scale(1.12); } }
.hero-slogan {
  position: absolute; left: 0; right: 0; bottom: 0;
  padding: 26px 20px 12px;
  background: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.55));
  color: #fff; font-size: 13px; letter-spacing: 3px;
}
.login-brand { display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 18px; }
.login-logo {
  width: 34px; height: 34px;
  animation: tiger-glow 2.6s ease-in-out infinite;
}
@keyframes tiger-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(249, 115, 22, 0); transform: scale(1); }
  50% { box-shadow: 0 0 16px 3px rgba(249, 115, 22, 0.5); transform: scale(1.06); }
}
.login-title { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: 1px; }
.login-form :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  box-shadow: 0 0 0 1px var(--border) inset;
  padding: 8px 12px;
  transition: box-shadow .18s ease;
}
.login-form :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px var(--accent) inset; }
.login-form :deep(.el-input.is-focus .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--accent) inset, 0 0 0 3px var(--accent-soft);
}
.login-form :deep(.el-button--primary) {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  border: none;
  box-shadow: 0 6px 16px rgba(249, 115, 22, 0.35);
  transition: transform .18s ease, box-shadow .18s ease;
}
.login-form :deep(.el-button--primary:hover) { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(249, 115, 22, 0.45); }
.login-form :deep(.el-button--primary:active) { transform: translateY(0); }
.switch-line { display: flex; justify-content: center; gap: 6px; margin-top: 4px; }
.captcha-row { display: flex; align-items: center; gap: 10px; width: 100%; }
.captcha-row :deep(.el-input__wrapper) { flex: 1; }
.captcha-img {
  height: 40px; width: 120px; object-fit: cover;
  border-radius: var(--radius-sm); cursor: pointer;
  box-shadow: 0 0 0 1px var(--border) inset;
}
</style>
