<script setup>
import { onMounted, ref } from 'vue'
import api from '../../lib/api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const d = await api.get('/me/tasks', { params: { page: page.value, size: size.value } })
    items.value = d.items || []
    total.value = d.total || 0
  } catch (e) { /* ignore */ } finally {
    loading.value = false
  }
}
onMounted(load)

const statusMap = {
  pending: ['排队中', 'info'],
  running: ['执行中', 'primary'],
  completed: ['成功', 'success'],
  failed: ['失败', 'danger'],
  cancelled: ['已取消', 'warning'],
  lost: ['丢失(已退款)', 'danger'],
}
const fmt = (v) => Number(v || 0).toLocaleString()
</script>

<template>
  <div class="card">
    <div class="card-head">
      <h3 class="card-title">历史任务</h3>
      <span class="muted">只列输出文件名，无文件预览/下载</span>
    </div>
    <el-skeleton v-if="loading" :rows="8" animated />
    <el-table v-else :data="items" empty-text="还没有任务（需先配 API Key 到 MCP 提交任务后自动归属）">
      <el-table-column label="任务 ID" min-width="170">
        <template #default="{ row }"><code>{{ row.mcp_task_id }}</code></template>
      </el-table-column>
      <el-table-column prop="workflow_name" label="工作流" min-width="150" />
      <el-table-column prop="instance" label="实例" width="120" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusMap[row.status]?.[1] || 'info'" size="small">
            {{ statusMap[row.status]?.[0] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="80">
        <template #default="{ row }">{{ row.duration_s != null ? row.duration_s + 's' : '—' }}</template>
      </el-table-column>
      <el-table-column label="积分" width="80">
        <template #default="{ row }">{{ fmt(row.billable_credits) }}</template>
      </el-table-column>
      <el-table-column label="输出文件" min-width="180">
        <template #default="{ row }">
          <span class="muted" v-if="row.outputs && row.outputs.length">{{ row.outputs.join(', ') }}</span>
          <span class="muted" v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="submitted_at" label="提交时间" width="170" />
    </el-table>
    <div class="pager" v-if="!loading">
      <el-pagination
        background layout="prev, pager, next, total"
        :total="total" :page-size="size" :current-page="page"
        @current-change="(p) => { page = p; load() }"
      />
    </div>
  </div>
</template>

<style scoped>
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { margin: 0; font-size: 16px; }
code { background: rgba(128,128,128,0.15); padding: 2px 6px; border-radius: 4px; }
.pager { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
