<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../lib/api'

const users = ref([])
const q = ref('')
const loading = ref(false)
const showDetail = ref(false)
const detail = ref(null)

const roleMap = { admin: ['管理员', 'warning'], user: ['普通用户', 'info'] }
const ledgerKind = {
  freeze: ['冻结', 'info'], settle: ['结算', 'danger'], refund: ['退款', 'success'],
  recharge: ['充值', 'success'], adjust: ['调整', 'warning'], seed: ['初始', 'info'],
}
const taskType = (s) =>
  s === 'completed' ? 'success' : s === 'failed' ? 'danger' : s === 'lost' ? 'warning' : 'info'
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  loading.value = true
  try {
    const d = await api.get('/admin/users', { params: { q: q.value } })
    users.value = d.users || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)

function adjust(u) {
  ElMessageBox.prompt(`调整 ${u.username} 的余额（正数加 / 负数扣）`, '调整余额', {
    confirmButtonText: '下一步', cancelButtonText: '取消', inputType: 'number',
    inputPlaceholder: 'delta，如 1000 或 -500',
  })
    .then(({ value }) =>
      ElMessageBox.prompt('备注', '调整余额', {
        confirmButtonText: '确定', cancelButtonText: '取消', inputPlaceholder: '原因（可选）',
      })
        .then(async ({ value: note }) => {
          const delta = parseInt(value, 10)
          if (!delta) return ElMessage.warning('delta 不能为 0')
          try {
            const r = await api.post(`/admin/users/${u.id}/adjust`, { delta, note: note || '' })
            ElMessage.success(`已调整，当前余额 ${fmt(r.balance)}`)
            load()
          } catch (e) { /* */ }
        })
        .catch(() => {})
    )
    .catch(() => {})
}

function toggleDisabled(u) {
  const act = u.disabled ? '启用' : '停用'
  ElMessageBox.confirm(`确认${act}用户 ${u.username}？`, '提示', { type: 'warning' })
    .then(async () => {
      try {
        await api.patch(`/admin/users/${u.id}`, { disabled: u.disabled ? 0 : 1 })
        ElMessage.success(`已${act}`)
        load()
      } catch (e) { /* */ }
    })
    .catch(() => {})
}

async function openDetail(u) {
  detail.value = { user: u, tokens: [], ledger: [], tasks: [], loading: true }
  showDetail.value = true
  try {
    const d = await api.get(`/admin/users/${u.id}`)
    detail.value = { user: d.user, tokens: d.tokens || [], ledger: d.ledger || [], tasks: d.tasks || [], loading: false }
  } catch (e) {
    showDetail.value = false
    detail.value = null
  }
}
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-input
        v-model="q" placeholder="按用户名搜索" clearable style="width: 240px"
        @keyup.enter="load" @clear="load"
      />
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <span class="muted">共 {{ users.length }} 个用户</span>
    </div>
    <el-table :data="users" v-loading="loading" empty-text="没有用户" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="roleMap[row.role]?.[1] || 'info'" size="small">{{ roleMap[row.role]?.[0] || row.role }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="余额" width="110">
        <template #default="{ row }">{{ fmt(row.balance) }}</template>
      </el-table-column>
      <el-table-column label="已用" width="100">
        <template #default="{ row }">{{ fmt(row.used) }}</template>
      </el-table-column>
      <el-table-column prop="task_count" label="任务数" width="90" />
      <el-table-column prop="active_count" label="在途" width="80" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '停用' : '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="注册时间" width="170" />
      <el-table-column label="操作" min-width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="adjust(row)">调额</el-button>
          <el-button size="small" type="warning" plain @click="openDetail(row)">详情</el-button>
          <el-button size="small" :type="row.disabled ? 'success' : 'danger'" plain @click="toggleDisabled(row)">
            {{ row.disabled ? '启用' : '停用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="showDetail" size="60%" :title="detail ? `用户 ${detail.user.username} 详情` : ''">
      <div v-if="detail && !detail.loading">
        <el-tabs>
          <el-tab-pane :label="`API Key（${detail.tokens.length}）`">
            <el-table :data="detail.tokens" empty-text="无 API Key" size="small">
              <el-table-column prop="name" label="名称" min-width="120" />
              <el-table-column prop="token_prefix" label="前缀" width="140">
                <template #default="{ row }"><code class="mono">{{ row.token_prefix }}…</code></template>
              </el-table-column>
              <el-table-column label="上限" width="90">
                <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.credit_limit) : '无上限' }}</template>
              </el-table-column>
              <el-table-column label="已用" width="90">
                <template #default="{ row }">{{ fmt(row.used) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '停用' : '正常' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="expires_at" label="过期" width="170">
                <template #default="{ row }"><span class="muted">{{ row.expires_at || '永不过期' }}</span></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`流水（${detail.ledger.length}）`">
            <el-table :data="detail.ledger" empty-text="无流水" size="small">
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag :type="ledgerKind[row.kind]?.[1] || 'info'" size="small">{{ ledgerKind[row.kind]?.[0] || row.kind }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="变动" width="100">
                <template #default="{ row }">
                  <span :style="{ color: row.delta < 0 ? 'var(--accent)' : '#67c23a', fontWeight: 600 }">{{ row.delta > 0 ? '+' : '' }}{{ fmt(row.delta) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="余额" width="100">
                <template #default="{ row }">{{ fmt(row.balance_after) }}</template>
              </el-table-column>
              <el-table-column prop="note" label="备注" min-width="160">
                <template #default="{ row }"><span class="muted">{{ row.note || '—' }}</span></template>
              </el-table-column>
              <el-table-column prop="created_at" label="时间" width="170" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`任务（${detail.tasks.length}）`">
            <el-table :data="detail.tasks" empty-text="无任务" size="small">
              <el-table-column prop="workflow_name" label="工作流" min-width="160" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="taskType(row.status)">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="积分" width="90">
                <template #default="{ row }">{{ fmt(row.billable_credits) }}</template>
              </el-table-column>
              <el-table-column prop="submitted_at" label="提交时间" width="170" />
              <el-table-column prop="finished_at" label="完成时间" width="170">
                <template #default="{ row }"><span class="muted">{{ row.finished_at || '—' }}</span></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
      <div v-else-if="detail" class="muted">加载中…</div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
</style>
