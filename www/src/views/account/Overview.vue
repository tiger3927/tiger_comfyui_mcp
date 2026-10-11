<script setup>
import { onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../../store/user'
import CountUp from '../../components/CountUp.vue'
import api from '../../lib/api'

const router = useRouter()
const route = useRoute()
const user = useUserStore()
const me = ref({})
const tokens = ref([])

// 复用组件自适配：admin 区（/admin/me/*）内跳「我的账户」子路由，用户端跳原路径（§7.2）
const myPath = (p) => (route.path.startsWith('/admin/me') ? `/admin/me${p}` : p)

async function load() {
  try { me.value = await user.fetchMe() } catch (e) { /* 401 跳登录 */ }
  try {
    const d = await api.get('/me/tokens')
    tokens.value = d.tokens || []
  } catch (e) { /* ignore */ }
}
onMounted(load)

const fmt = (v) => Number(v || 0).toLocaleString()
</script>

<template>
  <el-skeleton v-if="!me.id" :rows="6" animated />
  <div v-else>
    <div class="row-gap mb16">
      <div class="card balance-card flex1">
        <div class="lbl">可用余额（积分）</div>
        <div class="num"><CountUp :value="me.balance" /></div>
        <div class="lbl mt8">约 ¥{{ (Number(me.balance || 0) * 0.01).toFixed(2) }}</div>
      </div>
    </div>

    <div class="row-gap mb16">
      <div class="card flex1"><div class="stat-num"><CountUp :value="me.used" /></div><div class="stat-lbl">累计已用积分</div></div>
      <div class="card flex1"><div class="stat-num"><CountUp :value="me.today_credits" /></div><div class="stat-lbl">今日消耗</div></div>
      <div class="card flex1"><div class="stat-num"><CountUp :value="me.month_credits" /></div><div class="stat-lbl">本月消耗</div></div>
      <div class="card flex1"><div class="stat-num"><CountUp :value="tokens.length" /></div><div class="stat-lbl">API Key 数</div></div>
    </div>

    <div class="card">
      <div class="card-head">
        <h3 class="card-title">API Key 剩余可用一览</h3>
        <div>
          <el-button type="primary" size="small" @click="router.push(myPath('/recharge'))">充值</el-button>
          <el-button size="small" @click="router.push(myPath('/tokens'))">管理 API Key</el-button>
        </div>
      </div>
      <el-table :data="tokens" empty-text="还没有 API Key，去「API Key 管理」创建">
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="token_prefix" label="前缀" min-width="120">
          <template #default="{ row }"><code>{{ row.token_prefix }}…</code></template>
        </el-table-column>
        <el-table-column label="上限">
          <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.credit_limit) : '无上限' }}</template>
        </el-table-column>
        <el-table-column label="已用"><template #default="{ row }">{{ fmt(row.used) }}</template></el-table-column>
        <el-table-column label="剩余可用">
          <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.remaining) : '—' }}</template>
        </el-table-column>
        <el-table-column label="状态">
          <template #default="{ row }">
            <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">
              {{ row.disabled ? '停用' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { margin: 0; font-size: 16px; }
code { background: rgba(128,128,128,0.15); padding: 2px 6px; border-radius: 4px; }
</style>
