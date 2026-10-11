<script setup>
import { onMounted, ref, reactive } from 'vue'
import api from '../../lib/api'

const tasks = ref([])
const loading = ref(false)
const filter = reactive({ anonymous: false, uid: '', status: '' })

const statusType = (s) =>
  s === 'completed' ? 'success' : s === 'failed' ? 'danger'
    : s === 'cancelled' ? 'info' : s === 'lost' ? 'warning' : 'primary'
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  loading.value = true
  try {
    const params = {}
    if (filter.anonymous) params.anonymous = true
    if (filter.uid) params.uid = parseInt(filter.uid, 10)
    if (filter.status) params.status = filter.status
    const d = await api.get('/admin/tasks', { params })
    tasks.value = d.tasks || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-select v-model="filter.status" placeholder="状态" clearable style="width: 140px" @change="load">
        <el-option label="排队" value="pending" />
        <el-option label="执行中" value="running" />
        <el-option label="完成" value="completed" />
        <el-option label="失败" value="failed" />
        <el-option label="取消" value="cancelled" />
        <el-option label="丢失" value="lost" />
      </el-select>
      <el-input v-model="filter.uid" placeholder="用户 ID" clearable style="width: 120px" @keyup.enter="load" @clear="load" />
      <el-checkbox v-model="filter.anonymous" @change="load">仅匿名</el-checkbox>
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <span class="muted">共 {{ tasks.length }} 条</span>
    </div>
    <el-table :data="tasks" v-loading="loading" empty-text="没有任务" stripe>
      <el-table-column prop="mcp_task_id" label="任务 ID" width="130">
        <template #default="{ row }"><code class="mono">{{ row.mcp_task_id }}</code></template>
      </el-table-column>
      <el-table-column label="用户" width="90">
        <template #default="{ row }">{{ row.user_id || '匿名' }}</template>
      </el-table-column>
      <el-table-column prop="workflow_name" label="工作流" min-width="180" />
      <el-table-column prop="instance" label="实例" min-width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
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
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
</style>
