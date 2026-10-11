<script setup>
import { onMounted, ref } from 'vue'
import api from '../../lib/api'

const audit = ref([])
const loading = ref(false)

const actionType = (a) => {
  if (a.includes('disable_user')) return 'danger'
  if (a.includes('enable_user') || a.includes('confirm')) return 'success'
  if (a.includes('adjust') || a.includes('edit')) return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const d = await api.get('/admin/audit')
    audit.value = d.audit || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
      <span class="muted">最近 {{ audit.length }} 条管理操作</span>
    </div>
    <el-table :data="audit" v-loading="loading" empty-text="没有审计记录" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="admin_id" label="管理员" width="90" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target" label="目标" min-width="140">
        <template #default="{ row }"><code class="mono">{{ row.target }}</code></template>
      </el-table-column>
      <el-table-column prop="detail" label="详情" min-width="200">
        <template #default="{ row }"><span class="muted">{{ row.detail || '—' }}</span></template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="170" />
    </el-table>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
</style>
