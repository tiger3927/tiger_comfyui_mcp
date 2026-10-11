<script setup>
import { onMounted, ref, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../lib/api'

// 已知系统参数：k -> {label, desc, type}；后端未来新增 key 会自动出现在下方“其他参数”
const KNOWN = {
  new_user_bonus_credits: { label: '新用户注册赠送积分', desc: '新注册用户自动到账的积分（0=不赠送）', type: 'int' },
  registration_open: { label: '开放注册', desc: '1=开放注册；0=关闭（内测/公网策略）', type: 'bool' },
  allow_anonymous: { label: '允许匿名任务', desc: '1=放行匿名任务；0=必须带 API Key', type: 'bool' },
}

const values = ref({})
const loading = ref(false)
const saving = ref(false)
const ready = ref(false)

const knownRows = computed(() =>
  Object.keys(KNOWN).map((k) => ({ k, type: KNOWN[k].type, label: KNOWN[k].label, desc: KNOWN[k].desc })))
const otherRows = computed(() =>
  Object.keys(values.value).filter((k) => !(k in KNOWN)).map((k) => ({ k, v: values.value[k] })))

async function load() {
  loading.value = true
  try {
    const d = await api.get('/admin/settings')
    const s = { ...(d.settings || {}) }
    for (const k in KNOWN) {
      if (KNOWN[k].type === 'int' && s[k] != null) s[k] = Number(s[k]) || 0
    }
    values.value = s
    await nextTick()
    ready.value = true
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)

async function saveOne(k) {
  if (!ready.value) return
  saving.value = true
  try {
    const meta = KNOWN[k]
    let v = String(values.value[k] ?? '')
    if (meta && meta.type === 'int') v = String(Math.max(0, Number(v) || 0))
    if (meta && meta.type === 'bool') v = v === '0' ? '0' : '1'
    await api.post('/admin/settings', { k, v })
    ElMessage.success('已保存')
    load()
  } catch (e) { /* 拦截器已提示 */ } finally { saving.value = false }
}
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-button :loading="loading" @click="load">刷新</el-button>
      <span class="muted">系统参数（存 settings 表，可继续扩展；改动即时生效）</span>
    </div>

    <el-table :data="knownRows" v-loading="loading" stripe>
      <el-table-column label="参数" min-width="220">
        <template #default="{ row }">
          <div>{{ row.label }}</div>
          <div class="muted small">{{ row.desc }}</div>
        </template>
      </el-table-column>
      <el-table-column label="键 (key)" min-width="200">
        <template #default="{ row }"><code class="mono">{{ row.k }}</code></template>
      </el-table-column>
      <el-table-column label="值" min-width="200">
        <template #default="{ row }">
          <el-switch v-if="row.type === 'bool'" v-model="values[row.k]"
                     active-value="1" inactive-value="0" @change="saveOne(row.k)" />
          <el-input-number v-else-if="row.type === 'int'" v-model.number="values[row.k]"
                           :min="0" :step="1" :controls="false" style="width:100%"
                           @change="saveOne(row.k)" />
          <el-input v-else v-model="values[row.k]" @change="saveOne(row.k)" />
        </template>
      </el-table-column>
    </el-table>

    <h3 class="other-title">其他参数</h3>
    <el-table :data="otherRows" empty-text="暂无其他参数" stripe>
      <el-table-column label="键 (key)" min-width="220">
        <template #default="{ row }"><code class="mono">{{ row.k }}</code></template>
      </el-table-column>
      <el-table-column label="值（文本）" min-width="240">
        <template #default="{ row }">
          <el-input v-model="values[row.k]" @change="saveOne(row.k)" />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
.small { font-size: 12px; }
.other-title { margin: 20px 0 10px; font-size: 15px; }
</style>
