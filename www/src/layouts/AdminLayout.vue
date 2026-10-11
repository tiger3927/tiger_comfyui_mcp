<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../store/user'
import { useThemeStore } from '../store/theme'
import api from '../lib/api'
import { useIsMobile } from '../lib/responsive'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const theme = useThemeStore()
const refreshing = ref(false)
const { isMobile } = useIsMobile()
const drawerOpen = ref(false)
const logoSrc = import.meta.env.BASE_URL + 'assets/logo.svg'

const isDark = computed({
  get: () => theme.theme === 'dark',
  set: (v) => {
    theme.theme = v ? 'dark' : 'light'
    localStorage.setItem('tiger_portal_theme', theme.theme)
    theme.apply()
  },
})

async function refresh() {
  refreshing.value = true
  try {
    await user.fetchMe()
    ElMessage.success('已刷新')
  } finally {
    refreshing.value = false
  }
}

function changePassword() {
  ElMessageBox.prompt('旧密码', '修改密码', {
    confirmButtonText: '下一步',
    cancelButtonText: '取消',
    inputType: 'password',
  })
    .then(({ value: oldPwd }) =>
      ElMessageBox.prompt('新密码（≥8 位）', '修改密码', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputType: 'password',
      })
        .then(async ({ value: newPwd }) => {
          try {
            await api.post('/me/password', { old_password: oldPwd, new_password: newPwd })
            ElMessage.success('密码已修改')
          } catch (e) { /* 拦截器已提示 */ }
        })
        .catch(() => {})
    )
    .catch(() => {})
}

function logout() {
  user.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container class="app-shell">
    <!-- 桌面：固定侧栏 -->
    <el-aside v-if="!isMobile" width="220px" class="aside">
      <div class="brand">
        <img class="brand-logo" :src="logoSrc" alt="老虎C站" />
        <span class="brand-name">老虎C站</span>
      </div>
      <el-menu :default-active="route.path" router class="menu">
        <el-sub-menu index="me">
          <template #title><el-icon><UserFilled /></el-icon><span>我的账户</span></template>
          <el-menu-item index="/admin/me/overview"><el-icon><Odometer /></el-icon><span>账户总览</span></el-menu-item>
          <el-menu-item index="/admin/me/tokens"><el-icon><Key /></el-icon><span>我的 API Key</span></el-menu-item>
          <el-menu-item index="/admin/me/tasks"><el-icon><List /></el-icon><span>我的任务</span></el-menu-item>
          <el-menu-item index="/admin/me/expense"><el-icon><CreditCard /></el-icon><span>开支 / 流水</span></el-menu-item>
          <el-menu-item index="/admin/me/recharge"><el-icon><Wallet /></el-icon><span>充值</span></el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="platform">
          <template #title><el-icon><Grid /></el-icon><span>平台管理</span></template>
          <el-menu-item index="/admin/dashboard"><el-icon><DataAnalysis /></el-icon><span>系统看板</span></el-menu-item>
          <el-menu-item index="/admin/users"><el-icon><User /></el-icon><span>用户管理</span></el-menu-item>
          <el-menu-item index="/admin/tokens"><el-icon><Key /></el-icon><span>全平台 API Key</span></el-menu-item>
          <el-menu-item index="/admin/recharges"><el-icon><CreditCard /></el-icon><span>充值单</span></el-menu-item>
          <el-menu-item index="/admin/rules"><el-icon><Setting /></el-icon><span>计费规则</span></el-menu-item>
          <el-menu-item index="/admin/settings"><el-icon><Tools /></el-icon><span>系统参数</span></el-menu-item>
          <el-menu-item index="/admin/tasks"><el-icon><List /></el-icon><span>全平台任务</span></el-menu-item>
          <el-menu-item index="/admin/audit"><el-icon><Notebook /></el-icon><span>审计日志</span></el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <!-- 手机：左侧抽屉菜单（点菜单项自动关闭） -->
    <el-drawer
      v-if="isMobile"
      v-model="drawerOpen"
      direction="ltr"
      size="240px"
      :with-header="false"
      class="mobile-menu-drawer"
    >
      <div class="brand">
        <img class="brand-logo" :src="logoSrc" alt="老虎C站" />
        <span class="brand-name">老虎C站</span>
      </div>
      <el-menu :default-active="route.path" router class="menu" @select="drawerOpen = false">
        <el-sub-menu index="me">
          <template #title><el-icon><UserFilled /></el-icon><span>我的账户</span></template>
          <el-menu-item index="/admin/me/overview"><el-icon><Odometer /></el-icon><span>账户总览</span></el-menu-item>
          <el-menu-item index="/admin/me/tokens"><el-icon><Key /></el-icon><span>我的 API Key</span></el-menu-item>
          <el-menu-item index="/admin/me/tasks"><el-icon><List /></el-icon><span>我的任务</span></el-menu-item>
          <el-menu-item index="/admin/me/expense"><el-icon><CreditCard /></el-icon><span>开支 / 流水</span></el-menu-item>
          <el-menu-item index="/admin/me/recharge"><el-icon><Wallet /></el-icon><span>充值</span></el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="platform">
          <template #title><el-icon><Grid /></el-icon><span>平台管理</span></template>
          <el-menu-item index="/admin/dashboard"><el-icon><DataAnalysis /></el-icon><span>系统看板</span></el-menu-item>
          <el-menu-item index="/admin/users"><el-icon><User /></el-icon><span>用户管理</span></el-menu-item>
          <el-menu-item index="/admin/tokens"><el-icon><Key /></el-icon><span>全平台 API Key</span></el-menu-item>
          <el-menu-item index="/admin/recharges"><el-icon><CreditCard /></el-icon><span>充值单</span></el-menu-item>
          <el-menu-item index="/admin/rules"><el-icon><Setting /></el-icon><span>计费规则</span></el-menu-item>
          <el-menu-item index="/admin/settings"><el-icon><Tools /></el-icon><span>系统参数</span></el-menu-item>
          <el-menu-item index="/admin/tasks"><el-icon><List /></el-icon><span>全平台任务</span></el-menu-item>
          <el-menu-item index="/admin/audit"><el-icon><Notebook /></el-icon><span>审计日志</span></el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-drawer>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-button v-if="isMobile" text class="mobile-burger" aria-label="打开菜单" @click="drawerOpen = true">
            <el-icon><Menu /></el-icon>
          </el-button>
          <el-tag type="warning" size="small" class="desktop-only">管理员</el-tag>
          <el-button size="small" :loading="refreshing" @click="refresh">刷新</el-button>
          <span class="muted desktop-only" v-if="user.username">登录：{{ user.username }}</span>
        </div>
        <div class="header-right">
          <el-button size="small" @click="router.push({ name: 'me-overview' })">我的账户</el-button>
          <el-switch
            v-model="isDark"
            inline-prompt
            active-text="深色"
            inactive-text="浅色"
            style="margin-right: 12px"
          />
          <el-button size="small" @click="changePassword">改密码</el-button>
          <el-button size="small" type="danger" plain @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="main">
        <transition name="route-fade" mode="out-in">
          <RouterView v-slot="{ Component }">
            <component :is="Component" />
          </RouterView>
        </transition>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell { height: 100vh; }
/* 路由过渡：淡入 + 上移 */
.route-fade-enter-active, .route-fade-leave-active { transition: opacity .22s ease, transform .22s ease; }
.route-fade-enter-from { opacity: 0; transform: translateY(10px); }
.route-fade-leave-to { opacity: 0; transform: translateY(-6px); }
.aside { background: var(--card); border-right: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: 10px; padding: 18px 16px; }
.brand-logo {
  width: 34px; height: 34px; border-radius: var(--radius-sm);
  display: block; box-shadow: var(--shadow-sm);
}
.brand-name { font-weight: 700; font-size: 15px; }
.menu { border-right: none; }
.header {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--card); border-bottom: 1px solid var(--border);
  height: 56px;
}
.header-left, .header-right { display: flex; align-items: center; gap: 12px; }
.header-left .muted { margin-left: 4px; }
.main { background: var(--bg); }

/* 手机：header 换行 + 汉堡按钮 */
@media (max-width: 767px) {
  .header { flex-wrap: wrap; height: auto; padding: 8px 12px; row-gap: 8px; }
  .header-left, .header-right { flex-wrap: wrap; }
  .mobile-burger { margin-right: 2px; }
}
</style>
