import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '../store/user'
import MainLayout from '../layouts/MainLayout.vue'
import AdminLayout from '../layouts/AdminLayout.vue'

// hash 路由（§7.1）：生产刷新 /portal/ 任意 hash 都命中 index.html，无 404；
// 模拟支付深链接 /portal/#/pay/{order_no} 天然可用。
const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/pay/:orderNo', name: 'pay', component: () => import('../views/Pay.vue'), meta: { public: true } },
  // 用户端（普通用户 + 管理员均可访问；管理员登录后默认进 /admin，仍可回这里看自己账户）
  {
    path: '/',
    component: MainLayout,
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'overview', component: () => import('../views/account/Overview.vue') },
      { path: 'tokens', name: 'tokens', component: () => import('../views/account/Tokens.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('../views/account/Tasks.vue') },
      { path: 'expense', name: 'expense', component: () => import('../views/account/Expense.vue') },
      { path: 'recharge', name: 'recharge', component: () => import('../views/account/Recharge.vue') },
    ],
  },
  // 管理后台（§7.2：仅 role=admin；前端 requiresAdmin 守卫 + 后端 require_admin 双端保护）
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAuth: true, requiresAdmin: true },
    redirect: '/admin/dashboard',
    children: [
      // 我的账户（admin 也是用户：复用用户端组件，管理自己的 token / 充值 / 积分，§7.2）
      { path: 'me/overview', name: 'me-overview', component: () => import('../views/account/Overview.vue') },
      { path: 'me/tokens', name: 'me-tokens', component: () => import('../views/account/Tokens.vue') },
      { path: 'me/tasks', name: 'me-tasks', component: () => import('../views/account/Tasks.vue') },
      { path: 'me/expense', name: 'me-expense', component: () => import('../views/account/Expense.vue') },
      { path: 'me/recharge', name: 'me-recharge', component: () => import('../views/account/Recharge.vue') },
      // 平台管理
      { path: 'dashboard', name: 'admin-dashboard', component: () => import('../views/admin/Dashboard.vue') },
      { path: 'users', name: 'admin-users', component: () => import('../views/admin/Users.vue') },
      { path: 'tokens', name: 'admin-tokens', component: () => import('../views/admin/Tokens.vue') },
      { path: 'recharges', name: 'admin-recharges', component: () => import('../views/admin/Recharges.vue') },
      { path: 'rules', name: 'admin-rules', component: () => import('../views/admin/Rules.vue') },
      { path: 'settings', name: 'admin-settings', component: () => import('../views/admin/Settings.vue') },
      { path: 'comfyui', name: 'admin-comfyui', component: () => import('../views/admin/ComfyUI.vue'), meta: { title: '实例管理' } },
      { path: 'tasks', name: 'admin-tasks', component: () => import('../views/admin/Tasks.vue') },
      { path: 'audit', name: 'admin-audit', component: () => import('../views/admin/Audit.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes,
})

// 登录分流 + 角色守卫（§7.2）：
// - 未登录访问受保护页 → 登录（带 redirect）
// - 已登录但 user 未加载（刷新页面 token 在、role 未知）→ 先 fetchMe 拿 role
// - 已登录再访问登录页 → 按 role 分流（admin→/admin，普通用户→/）
// - 非管理员访问 /admin → 回用户端
router.beforeEach(async (to) => {
  const store = useUserStore()
  if (to.meta.requiresAuth && !store.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAuth && store.isLoggedIn && !store.user) {
    try {
      await store.fetchMe()
    } catch (e) {
      /* 401 拦截器已清 token 并跳登录 */
    }
    if (!store.isLoggedIn) return { name: 'login' }
  }
  if (to.name === 'login' && store.isLoggedIn) {
    return { name: store.isAdmin ? 'admin-dashboard' : 'overview' }
  }
  if (to.meta.requiresAdmin && !store.isAdmin) {
    return { name: 'overview' }
  }
  return true
})

export default router
