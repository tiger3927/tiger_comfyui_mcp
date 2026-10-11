<script setup>
import { onMounted, ref } from 'vue'
import api from '../../lib/api'

const tokens = ref([])
const loading = ref(false)
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  loading.value = true
  try {
    const d = await api.get('/admin/tokens')
    tokens.value = d.tokens || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
      <span class="muted">全平台共 {{ tokens.length }} 个 API Key</span>
    </div>
    <el-table :data="tokens" v-loading="loading" empty-text="没有 API Key" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="所属用户" min-width="130" />
      <el-table-column prop="name" label="名称" min-width="130" />
      <el-table-column prop="token_prefix" label="前缀" width="150">
        <template #default="{ row }"><code class="mono">{{ row.token_prefix }}…</code></template>
      </el-table-column>
      <el-table-column label="上限" width="100">
        <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.credit_limit) : '无上限' }}</template>
      </el-table-column>
      <el-table-column label="已用" width="100">
        <template #default="{ row }">{{ fmt(row.used) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '停用' : '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="expires_at" label="过期时间" width="170">
        <template #default="{ row }"><span class="muted">{{ row.expires_at || '永不过期' }}</span></template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
</style>
