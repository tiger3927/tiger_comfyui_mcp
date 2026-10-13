<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import api from '../../lib/api'
import { VChart } from '../../lib/echarts'
import { useThemeStore } from '../../store/theme'

const theme = useThemeStore()
const isDark = computed(() => theme.theme === 'dark')
const range = ref(30)
const loading = ref(false)
const data = ref(null)

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/admin/stats', { params: { days: range.value } })
  } catch (e) { /* 拦截器已提示 */ }
  finally {
    loading.value = false
  }
}
onMounted(load)
watch(range, load)

const kpi = computed(() => data.value?.kpi || {})
const fmt = (v) => Number(v || 0).toLocaleString()
const pct = (v) => (v != null ? (v * 100).toFixed(1) + '%' : '—')

// 主题相关颜色（ECharts 文字/网格跟随暗色）
const textColor = computed(() => (isDark.value ? '#cfd3dc' : '#606266'))
const axisLineColor = computed(() => (isDark.value ? '#4c4d4f' : '#e4e7ed'))
const splitLineColor = computed(() => (isDark.value ? '#363739' : '#ebeef5'))

// ---------------- 饼图 ----------------
function makePie(items) {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)', textStyle: { color: textColor.value } },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: textColor.value, fontSize: 11 } },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        itemStyle: { borderColor: isDark.value ? '#1c1c1e' : '#fff', borderWidth: 2 },
        label: { color: textColor.value, formatter: '{d}%', fontSize: 11 },
        labelLine: { lineStyle: { color: textColor.value } },
        data: items || [],
      },
    ],
  }
}
const pieKeys = [
  ['task_status', '任务状态分布'],
  ['credit_flow', '积分流向'],
  ['workflow_top', '工作流 Top10'],
  ['media', '媒体类型'],
  ['instance', '实例任务分布'],
  ['recharge_status', '充值订单状态'],
]

// ---------------- 实例总览（实时探针 + 窗口内聚合）----------------
const GB = 1073741824
const instances = computed(() => data.value?.instances || [])
const gpus = (row) => (row.devices || []).map((d) => {
  const name = String(d.name || '').replace(/\bcuda:\d+\s*/i, '').replace(/ : .*$/, '')
  return `${name} ${((d.vram_free || 0) / GB).toFixed(1)}/${((d.vram_total || 0) / GB).toFixed(0)}GB`
}).join('；') || '—'
const pieCharts = computed(() =>
  pieKeys.map(([key, title]) => ({
    key, title,
    option: makePie(data.value?.pie?.[key]),
    empty: !(data.value?.pie?.[key] && data.value?.pie?.[key].length),
  })))

// ---------------- 曲线 ----------------
const dates = computed(() => data.value?.trend?.dates || [])
const mmdd = (v) => (v ? String(v).slice(5) : '')

function baseLine() {
  return {
    tooltip: { trigger: 'axis', textStyle: { color: textColor.value } },
    legend: { top: 0, textStyle: { color: textColor.value, fontSize: 11 } },
    grid: { left: 50, right: 22, top: 32, bottom: 28 },
    xAxis: {
      type: 'category',
      data: dates.value,
      axisLabel: { color: textColor.value, fontSize: 10, formatter: mmdd },
      axisLine: { lineStyle: { color: axisLineColor.value } },
    },
  }
}
const valAxis = () => ({
  type: 'value',
  axisLabel: { color: textColor.value },
  splitLine: { lineStyle: { color: splitLineColor.value } },
})

// 1 积分消耗（面积）
const consumeOpt = computed(() => {
  const o = baseLine()
  o.yAxis = valAxis()
  o.series = [{
    name: '积分', type: 'line', smooth: true, areaStyle: { opacity: 0.25 },
    data: (data.value?.trend?.consume || []).map((x) => x.v),
  }]
  return o
})
// 2 任务量（total/completed/failed）
const tasksOpt = computed(() => {
  const t = data.value?.trend?.tasks || []
  const o = baseLine()
  o.yAxis = valAxis()
  o.series = [
    { name: '总量', type: 'line', smooth: true, data: t.map((x) => x.total) },
    { name: '成功', type: 'line', smooth: true, data: t.map((x) => x.completed) },
    { name: '失败', type: 'line', smooth: true, data: t.map((x) => x.failed) },
  ]
  return o
})
// 3 充值（积分 + 金额 双轴）
const rechargeOpt = computed(() => {
  const t = data.value?.trend?.recharge || []
  const o = baseLine()
  o.yAxis = [
    { ...valAxis(), name: '积分' },
    { ...valAxis(), name: '¥', splitLine: { show: false } },
  ]
  o.series = [
    { name: '积分', type: 'line', smooth: true, areaStyle: { opacity: 0.2 }, data: t.map((x) => x.credits) },
    { name: '金额(¥)', type: 'line', yAxisIndex: 1, smooth: true, data: t.map((x) => x.rmb) },
  ]
  return o
})
// 4 用户增长（累计折线 + 新增柱）
const usersOpt = computed(() => {
  const t = data.value?.trend?.users || []
  const o = baseLine()
  o.yAxis = valAxis()
  o.series = [
    { name: '累计', type: 'line', smooth: true, areaStyle: { opacity: 0.15 }, data: t.map((x) => x.total) },
    { name: '新增', type: 'bar', barWidth: '40%', data: t.map((x) => x.new) },
  ]
  return o
})
// 5 成功率（0-100%）
const successOpt = computed(() => {
  const t = data.value?.trend?.success_rate || []
  const o = baseLine()
  o.yAxis = {
    type: 'value', min: 0, max: 1, interval: 0.25,
    axisLabel: { color: textColor.value, formatter: (v) => (v * 100) + '%' },
    splitLine: { lineStyle: { color: splitLineColor.value } },
  }
  o.series = [{
    name: '成功率', type: 'line', smooth: true, connectNulls: true,
    data: t.map((x) => (x.v != null ? +(x.v * 100).toFixed(1) : null)),
  }]
  return o
})
// 6 平均耗时
const durationOpt = computed(() => {
  const t = data.value?.trend?.duration || []
  const o = baseLine()
  o.yAxis = { ...valAxis(), name: '秒' }
  o.series = [{
    name: '平均耗时(s)', type: 'line', smooth: true, connectNulls: true,
    data: t.map((x) => x.v),
  }]
  return o
})
// 7 实例成功率对比（横向柱，仅展示有成败记录的实例）
const instSuccessOpt = computed(() => {
  const rows = instances.value
    .filter((x) => x.success_rate != null)
    .sort((a, b) => b.success_rate - a.success_rate)
  const o = baseLine()
  o.tooltip.formatter = '{b}: {c}%'
  o.xAxis = { ...valAxis(), max: 100 }
  o.yAxis = {
    type: 'category', inverse: true, data: rows.map((r) => r.name),
    axisLabel: { color: textColor.value, fontSize: 10 },
    axisLine: { lineStyle: { color: axisLineColor.value } },
  }
  o.series = [{
    name: '成功率(%)', type: 'bar', barWidth: '50%',
    data: rows.map((r) => +(r.success_rate * 100).toFixed(1)),
    label: { show: true, position: 'right', color: textColor.value,
      formatter: (p) => p.value + '%' },
  }]
  return o
})
const lineCharts = computed(() => [
  { key: 'consume', title: '积分消耗趋势', option: consumeOpt.value },
  { key: 'tasks', title: '任务量趋势', option: tasksOpt.value },
  { key: 'recharge', title: '充值趋势（积分/金额）', option: rechargeOpt.value },
  { key: 'users', title: '用户增长（累计/新增）', option: usersOpt.value },
  { key: 'success', title: '成功率趋势', option: successOpt.value },
  { key: 'duration', title: '平均耗时趋势', option: durationOpt.value },
  { key: 'inst-success', title: `实例成功率对比（近 ${range.value} 天）`, option: instSuccessOpt.value },
])
</script>

<template>
  <div class="row-gap">
    <!-- 工具栏 -->
    <div class="card toolbar">
      <el-radio-group v-model="range" size="small">
        <el-radio-button :label="7">近 7 天</el-radio-button>
        <el-radio-button :label="30">近 30 天</el-radio-button>
        <el-radio-button :label="90">近 90 天</el-radio-button>
      </el-radio-group>
      <div class="toolbar-right">
        <span class="muted" v-if="data?.generated_at">数据时间 {{ data.generated_at }}</span>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- KPI 指标卡（响应式：手机 2 列 / 平板 3 列 / 桌面 6 列） -->
    <el-row :gutter="14" class="gap-row">
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">用户总数</div>
          <div class="kpi-num">{{ fmt(kpi.user_total) }}</div>
          <div class="kpi-sub">{{ kpi.admin_count || 0 }} 管理员 · {{ kpi.user_count || 0 }} 用户</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">平台总余额</div>
          <div class="kpi-num">{{ fmt(kpi.total_balance) }}</div>
          <div class="kpi-sub">约 ¥{{ fmt(kpi.total_balance_rmb) }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">累计充值</div>
          <div class="kpi-num">¥{{ fmt(kpi.recharge_rmb) }}</div>
          <div class="kpi-sub">{{ fmt(kpi.recharge_credits) }} 积分</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">累计消耗</div>
          <div class="kpi-num">{{ fmt(kpi.consumed_credits) }}</div>
          <div class="kpi-sub">积分（成功+取消）</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">任务总数</div>
          <div class="kpi-num">{{ fmt(kpi.task_total) }}</div>
          <div class="kpi-sub">成功率 {{ pct(kpi.task_success_rate) }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6" :lg="4" class="kpi-col">
        <div class="card kpi">
          <div class="kpi-lbl">在途任务</div>
          <div class="kpi-num">{{ fmt(kpi.task_active) }}</div>
          <div class="kpi-sub">pending / running</div>
        </div>
      </el-col>
    </el-row>

    <!-- 饼图（响应式：手机 1 列 / 平板 2 列 / 桌面 3 列） -->
    <el-row :gutter="14" class="gap-row">
      <el-col :xs="24" :sm="12" :lg="8" v-for="p in pieCharts" :key="p.key">
        <div class="card chart-card">
          <div class="chart-title">{{ p.title }}</div>
          <VChart v-if="!p.empty" :option="p.option" class="chart" autoresize />
          <div class="chart-empty muted" v-else>暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <!-- 时间曲线（响应式：手机 1 列 / 桌面 2 列） -->
    <el-row :gutter="14" class="gap-row">
      <el-col :xs="24" :lg="12" v-for="c in lineCharts" :key="c.key">
        <div class="card chart-card">
          <div class="chart-title">{{ c.title }}</div>
          <VChart :option="c.option" class="chart" autoresize />
        </div>
      </el-col>
    </el-row>

    <!-- 实例总览（实时状态 + 窗口内聚合）：纳入 2 列网格 lg=12，与曲线图卡同宽（标准卡宽）。
         注意：页面根 .row-gap 是 flex-wrap，子项默认收缩包裹 → el-row 必须 width:100% 才占满整行；
         列全 min-width，卡宽够时撑满、不够时 el-table 横滚；行数多 max-height 纵滚 -->
    <el-row :gutter="14" class="gap-row inst-row" v-if="instances.length">
      <el-col :xs="24" :lg="12">
        <div class="card inst-card">
          <div class="chart-title">ComfyUI 实例总览（近 {{ range }} 天）</div>
          <el-table :data="instances" size="small" stripe :max-height="460">
            <el-table-column label="实例" min-width="100">
              <template #default="{ row }">
                <span>{{ row.name }}</span>
                <el-tag v-if="row.is_default" type="warning" size="small" style="margin-left: 6px">默认</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <el-tag v-if="row.connected" type="success" size="small">在线</el-tag>
                <el-tooltip v-else :content="row.error || '不可达'" placement="top">
                  <el-tag type="danger" size="small">离线</el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="GPU / 显存(可用/总量)" min-width="160">
              <template #default="{ row }">{{ gpus(row) }}</template>
            </el-table-column>
            <el-table-column label="ComfyUI 队列(排队/执行)" min-width="80">
              <template #default="{ row }">
                {{ row.connected ? `${row.queue_pending ?? 0} / ${row.queue_running ?? 0}` : '—' }}
              </template>
            </el-table-column>
            <el-table-column prop="tasks_active" label="服务在途" min-width="60" />
            <el-table-column prop="tasks_total" label="窗口任务" min-width="60" />
            <el-table-column label="成功率" min-width="64">
              <template #default="{ row }">{{ row.success_rate != null ? (row.success_rate * 100).toFixed(1) + '%' : '—' }}</template>
            </el-table-column>
            <el-table-column label="平均耗时" min-width="70">
              <template #default="{ row }">{{ row.dur_avg != null ? row.dur_avg + 's' : '—' }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.gap-row { row-gap: 14px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }
.kpi-col { display: flex; flex-direction: column; }
.kpi { flex: 1; padding: 14px 16px; display: flex; flex-direction: column; }
.kpi-lbl { font-size: 12px; color: #909399; }
.kpi-num { font-size: 24px; font-weight: 700; margin: 4px 0; }
.kpi-sub { font-size: 12px; color: #909399; margin-top: auto; line-height: 1.4; }
.chart-card { padding: 14px 16px; }
.chart-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.chart { width: 100%; height: 260px; }
.chart-empty { height: 260px; display: flex; align-items: center; justify-content: center; }
/* 实例总览：行必须撑满 flex 容器（根 .row-gap 是 flex-wrap，子项默认收缩包裹）；
   卡宽由 el-col lg=12 决定，与曲线图卡同宽 */
.inst-row { width: 100%; }
.inst-card { padding: 14px 16px; }

/* 手机：KPI/饼图/曲线行的自然宽 = 容器+14（EP gutter 负 margin，内容撑到 364）；
   本行同步 +14 并禁止 flex 收缩，实例卡 = 350，与 KPI/饼图/曲线卡同宽对齐。
   桌面端不受影响（仍 width:100%，与其他行同宽） */
@media (max-width: 575px) {
  .inst-row { width: calc(100% + 14px); flex-shrink: 0; max-width: 364px; }
}

/* 手机：图表高度收紧 */
@media (max-width: 767px) {
  .chart, .chart-empty { height: 220px; }
}
</style>
