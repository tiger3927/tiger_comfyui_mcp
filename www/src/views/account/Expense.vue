<script setup>
import { onMounted, ref } from 'vue'
import api from '../../lib/api'

const tab = ref('ledger')
const ledger = ref({ items: [], total: 0, page: 1 })
const recharges = ref([])

const kindMap = {
  freeze: ['冻结', 'info'],
  settle: ['结算', 'danger'],
  refund: ['退款', 'success'],
  recharge: ['充值', 'success'],
  adjust: ['调整', 'warning'],
  seed: ['初始', 'info'],
}
const statusMap = {
  pending: ['待付款', 'warning'],
  paid: ['已付款', 'primary'],
  credited: ['已到账', 'success'],
  cancelled: ['已作废', 'info'],
}

async function loadLedger() {
  try {
    const d = await api.get('/me/ledger', { params: { page: ledger.value.page, size: 20 } })
    ledger.value.items = d.items || []
    ledger.value.total = d.total || 0
  } catch (e) { /* ignore */ }
}
async function loadRecharges() {
  try {
    const d = await api.get('/me/recharges')
    recharges.value = d.recharges || []
  } catch (e) { /* ignore */ }
}
onMounted(() => { loadLedger(); loadRecharges() })

const fmt = (v) => Number(v || 0).toLocaleString()
</script>

<template>
  <div class="card">
    <el-tabs v-model="tab" @tab-change="(t) => (t === 'ledger' ? loadLedger() : loadRecharges())">
      <el-tab-pane label="开支明细" name="ledger">
        <el-table :data="ledger.items" empty-text="还没有流水">
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="kindMap[row.kind]?.[1] || 'info'" size="small">{{ kindMap[row.kind]?.[0] || row.kind }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="变动" width="110">
            <template #default="{ row }">
              <span :style="{ color: row.delta < 0 ? 'var(--accent)' : '#67c23a', fontWeight: 600 }">
                {{ row.delta > 0 ? '+' : '' }}{{ fmt(row.delta) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="余额" width="110">
            <template #default="{ row }">{{ fmt(row.balance_after) }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="180">
            <template #default="{ row }"><span class="muted">{{ row.note || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="170" />
        </el-table>
        <div class="pager">
          <el-pagination
            background layout="prev, pager, next, total"
            :total="ledger.total" :page-size="20" :current-page="ledger.page"
            @current-change="(p) => { ledger.page = p; loadLedger() }"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="充值记录" name="recharges">
        <el-table :data="recharges" empty-text="还没有充值">
          <el-table-column prop="order_no" label="订单号" min-width="190" />
          <el-table-column label="金额" width="100">
            <template #default="{ row }">¥{{ row.amount_rmb }}</template>
          </el-table-column>
          <el-table-column label="积分" width="100">
            <template #default="{ row }">{{ fmt(row.credits) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="statusMap[row.status]?.[1] || 'info'" size="small">{{ statusMap[row.status]?.[0] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="170" />
          <el-table-column label="到账时间" width="170">
            <template #default="{ row }"><span class="muted">{{ row.credited_at || '—' }}</span></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.pager { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
