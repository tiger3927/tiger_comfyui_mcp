<script setup>
import { ref, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../lib/api'
import QRCode from 'qrcode'

const amounts = [100, 200, 500, 1000]
const amount = ref(100)
const order = ref(null)
const qr = ref('')
const polling = ref(null)
const creating = ref(false)

// 积分换算：rmb_per_credit=0.01 → 1 元 = 100 积分
const credits = () => Math.round(amount.value / 0.01)

async function createOrder() {
  creating.value = true
  try {
    const d = await api.post('/recharges', { amount: amount.value })
    order.value = d
    const hashUrl = `${window.location.origin}${import.meta.env.BASE_URL}#/pay/${d.order_no}`
    qr.value = await QRCode.toDataURL(hashUrl, { width: 220, margin: 1 })
    startPolling(d.order_no)
  } catch (e) { /* 拦截器已提示 */ }
  finally {
    creating.value = false
  }
}

function startPolling(orderNo) {
  stopPolling()
  polling.value = setInterval(async () => {
    try {
      const r = await api.get(`/recharges/${orderNo}`)
      if (r.status === 'credited') {
        stopPolling()
        order.value = r
        ElMessage.success('充值到账！')
      }
    } catch (e) { /* ignore */ }
  }, 3000)
}
function stopPolling() {
  if (polling.value) {
    clearInterval(polling.value)
    polling.value = null
  }
}
onUnmounted(stopPolling)

const statusMap = {
  pending: ['待付款', 'warning'],
  paid: ['已付款', 'primary'],
  credited: ['已到账', 'success'],
  cancelled: ['已作废', 'info'],
}
</script>

<template>
  <div class="row-gap">
    <div class="card flex1">
      <h3 class="card-title">充值</h3>
      <p class="muted">模拟支付 · 三方支付接入中。1 元 = 100 积分。</p>
      <div class="amount-row">
        <el-button
          v-for="a in amounts" :key="a"
          :type="amount === a ? 'primary' : 'default'"
          @click="amount = a"
        >
          ¥{{ a }}
        </el-button>
      </div>
      <p class="mt16">
        当前：¥{{ amount }} → <b>{{ credits() }}</b> 积分
      </p>
      <el-button type="primary" size="large" :loading="creating" @click="createOrder">
        生成充值订单
      </el-button>
    </div>

    <div class="card flex1" v-if="order">
      <h3 class="card-title">扫码支付</h3>
      <div class="qr-box">
        <img v-if="qr" :src="qr" alt="二维码" @error="e => (e.target.outerHTML = '<div class=muted>二维码加载失败</div>')" />
        <div class="muted" v-else>生成中…</div>
      </div>
      <p class="muted" style="text-align: center">
        订单号：<code>{{ order.order_no }}</code>
      </p>
      <el-alert
        :title="order.status === 'credited' ? '已到账' : '请扫码后在支付页点「确认付款（模拟）」'"
        :type="order.status === 'credited' ? 'success' : 'info'"
        :closable="false"
      />
      <div class="mt8" style="text-align: center">
        <el-tag :type="statusMap[order.status]?.[1] || 'info'">{{ statusMap[order.status]?.[0] || order.status }}</el-tag>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card-title { margin: 0 0 8px; font-size: 16px; }
.amount-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
code { background: rgba(128,128,128,0.15); padding: 2px 6px; border-radius: 4px; }
</style>
