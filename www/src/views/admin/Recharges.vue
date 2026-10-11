<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../lib/api'

const recharges = ref([])
const loading = ref(false)
const filter = ref({ status: '', uid: '' })

const statusMap = {
  pending: ['待付款', 'warning'], paid: ['已付款', 'primary'],
  credited: ['已到账', 'success'], cancelled: ['已作废', 'info'],
}
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  loading.value = true
  try {
    const params = {}
    if (filter.value.status) params.status = filter.value.status
    if (filter.value.uid) params.uid = parseInt(filter.value.uid, 10)
    const d = await api.get('/admin/recharges', { params })
    recharges.value = d.recharges || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)

function confirmOrder(r) {
  ElMessageBox.confirm(`确认订单 ${r.order_no} 入账 ${fmt(r.credits)} 积分？`, '确认入账', { type: 'warning' })
    .then(async () => {
      try {
        const res = await api.post(`/admin/recharges/${r.order_no}/confirm`)
        ElMessage.success(res.status === 'credited' ? '已入账' : '已是入账状态')
        load()
      } catch (e) { /* */ }
    }).catch(() => {})
}
function cancelOrder(r) {
  ElMessageBox.confirm(`作废订单 ${r.order_no}？`, '作废', { type: 'warning' })
    .then(async () => {
      try {
        await api.post(`/admin/recharges/${r.order_no}/cancel`)
        ElMessage.success('已作废')
        load()
      } catch (e) { /* */ }
    }).catch(() => {})
}
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-select v-model="filter.status" placeholder="状态" clearable style="width: 140px" @change="load">
        <el-option label="待付款" value="pending" />
        <el-option label="已付款" value="paid" />
        <el-option label="已到账" value="credited" />
        <el-option label="已作废" value="cancelled" />
      </el-select>
      <el-input v-model="filter.uid" placeholder="用户 ID" clearable style="width: 120px" @keyup.enter="load" @clear="load" />
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <span class="muted">共 {{ recharges.length }} 单</span>
    </div>
    <el-table :data="recharges" v-loading="loading" empty-text="没有充值单" stripe>
      <el-table-column prop="order_no" label="订单号" min-width="200" />
      <el-table-column prop="username" label="用户" min-width="120" />
      <el-table-column label="金额" width="90">
        <template #default="{ row }">¥{{ row.amount_rmb }}</template>
      </el-table-column>
      <el-table-column label="积分" width="100">
        <template #default="{ row }">{{ fmt(row.credits) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusMap[row.status]?.[1] || 'info'" size="small">{{ statusMap[row.status]?.[0] || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button v-if="row.status === 'paid'" size="small" type="success" @click="confirmOrder(row)">确认入账</el-button>
          <el-button v-if="row.status === 'pending'" size="small" type="danger" plain @click="cancelOrder(row)">作废</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
</style>
