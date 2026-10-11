<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../lib/api'

const route = useRoute()
const order = ref({})
const loading = ref(false)

async function load() {
  try {
    order.value = await api.get(`/pay/${route.params.orderNo}`)
  } catch (e) { /* 订单不存在等 */ }
}
onMounted(load)

async function confirm() {
  loading.value = true
  try {
    const r = await api.post(`/pay/${route.params.orderNo}/confirm`)
    order.value.status = r.status
    ElMessage.success(r.status === 'credited' ? '付款成功，积分已到账' : '已付款，等待管理员确认后到账')
    load()
  } finally {
    loading.value = false
  }
}

const statusMap = {
  pending: ['待付款', 'warning'],
  paid: ['已付款，待确认', 'primary'],
  credited: ['已到账', 'success'],
  cancelled: ['已作废', 'info'],
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card" v-if="order.order_no">
      <h2 class="login-title">模拟支付</h2>
      <p class="login-sub">扫码目标页（匿名可达）· 三方支付接入中</p>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="订单号">{{ order.order_no }}</el-descriptions-item>
        <el-descriptions-item label="金额">¥{{ order.amount_rmb }}</el-descriptions-item>
        <el-descriptions-item label="到账积分">{{ order.credits }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusMap[order.status]?.[1] || 'info'">
            {{ statusMap[order.status]?.[0] || order.status }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-button
        type="primary" size="large" style="width: 100%; margin-top: 20px"
        :loading="loading" :disabled="order.status === 'credited' || order.status === 'cancelled'"
        @click="confirm"
      >
        {{ order.status === 'credited' ? '已到账' : order.status === 'paid' ? '确认付款（模拟）' : '确认付款（模拟）' }}
      </el-button>
    </el-card>
    <el-card class="login-card" v-else>
      <h2 class="login-title">订单不存在</h2>
      <p class="login-sub muted">请核对二维码或订单号</p>
    </el-card>
  </div>
</template>
