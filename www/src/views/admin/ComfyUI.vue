<script setup>
// 实例管理专区（Task-DB-Config §4）：
// 左栏实例卡片（active 徽标 / default 星标 / sort 上下移）；
// 右栏 Tab1 实例设置（url/password/启用/删除）+ Tab2 勾选矩阵（白名单/only/exclude）
// + Tab3 高级（default/权重/手术制度）。所有写操作落审计、服务端写前整体校验。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../lib/api'

// ---------------------------------------------------------------- state
const instances = ref([])
const whitelist = ref([])      // [{id, pattern, active}]
const wfNames = ref([])
const advanced = ref({ default_instance: '', pending: 1.0, running: 2.0, prune_modes: {} })
const advDraft = ref({ pending: 1.0, running: 2.0 })
const defaultDraft = ref('')
const pruneDraft = ref([])     // [{key, mode}]
const loading = ref(false)
const selected = ref(null)     // 选中实例对象

const tab = ref('settings')
const saving = ref(false)

// 新建实例弹窗
const createDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', url: '', password: '' })

// Tab1 表单草稿
const urlDraft = ref('')
const pwdDraft = ref('')

// Tab2 矩阵草稿：{ [wfName]: {wl, only, excl} }
const matrix = ref({})

// ---------------------------------------------------------------- helpers
const sortedInstances = computed(() =>
  [...instances.value].sort((a, b) => (a.sort - b.sort) || (a.id - b.id)))
const defaultName = computed(() => advanced.value.default_instance || '')
const wlActive = computed(() => new Set(
  whitelist.value.filter((e) => e.active).map((e) => e.pattern)))

function instanceById(id) {
  return instances.value.find((i) => i.id === id) || null
}

// ---------------------------------------------------------------- load
async function load() {
  loading.value = true
  try {
    const [dInst, dWl, dNames, dAdv] = await Promise.all([
      api.get('/admin/comfyui/instances'),
      api.get('/admin/comfyui/whitelist'),
      api.get('/admin/comfyui/workflow-names'),
      api.get('/admin/comfyui/advanced'),
    ])
    instances.value = dInst.instances || []
    whitelist.value = dWl.entries || []
    wfNames.value = dNames.names || []
    advanced.value = dAdv
    advDraft.value = { pending: dAdv.pending, running: dAdv.running }
    defaultDraft.value = dAdv.default_instance || ''
    pruneDraft.value = Object.entries(dAdv.prune_modes || {}).map(
      ([k, mode]) => ({ key: k, mode }))
    if (!selected.value) {
      const first = sortedInstances.value.find((i) => i.active)
        || sortedInstances.value[0]
      if (first) selectInstance(first)
    } else {
      const cur = instances.value.find((i) => i.id === selected.value.id)
      if (cur) selectInstance(cur)
      else selectInstance(sortedInstances.value[0] || null)
    }
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)

function selectInstance(inst) {
  if (!inst) return
  selected.value = inst
  tab.value = 'settings'
  urlDraft.value = inst.url
  pwdDraft.value = inst.password || ''
  buildMatrix(inst)
}

function buildMatrix(inst) {
  const m = {}
  for (const name of wfNames.value) {
    m[name] = {
      wl: wlActive.value.has(name),
      only: (inst.only || []).includes(name),
      excl: (inst.exclude || []).includes(name),
    }
  }
  matrix.value = m
}

// ---------------------------------------------------------------- Tab1
async function saveSettings() {
  if (!selected.value) return
  saving.value = true
  try {
    await api.patch(`/admin/comfyui/instances/${selected.value.id}`, {
      url: urlDraft.value,
      password: pwdDraft.value,
      active: selected.value.active,
    })
    ElMessage.success('已保存')
    await load()
  } catch (e) { /* */ } finally { saving.value = false }
}

async function toggleActive() {
  if (!selected.value) return
  try {
    await api.patch(`/admin/comfyui/instances/${selected.value.id}`, {
      active: selected.value.active ? 0 : 1,
    })
    ElMessage.success(selected.value.active ? '已禁用' : '已启用')
    await load()
  } catch (e) { /* */ }
}

async function removeInstance() {
  if (!selected.value) return
  const inst = selected.value
  try {
    await ElMessageBox.confirm(
      `确认物理删除实例 ${inst.name}？其工作流规则会一并删除。`
      + '有在途任务或为默认实例时服务端会拦截。',
      '删除实例', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch (e) { return }
  try {
    await api.delete(`/admin/comfyui/instances/${inst.id}`)
    ElMessage.success('已删除')
    selected.value = null
    await load()
  } catch (e) { /* 拦截器已提示（含拦截原因） */ }
}

// ---------------------------------------------------------------- 左栏
async function createInstance() {
  const f = createForm.value
  if (!f.name.trim()) return ElMessage.warning('实例名必填')
  if (!f.url.trim()) return ElMessage.warning('URL 必填')
  creating.value = true
  try {
    const d = await api.post('/admin/comfyui/instances', {
      name: f.name.trim(), url: f.url.trim(), password: f.password,
    })
    ElMessage.success('已创建')
    createDialog.value = false
    createForm.value = { name: '', url: '', password: '' }
    await load()
    const created = instances.value.find((i) => i.id === d.id)
    if (created) selectInstance(created)
  } catch (e) { /* */ } finally { creating.value = false }
}

async function move(id, dir) {
  const list = sortedInstances.value
  const idx = list.findIndex((i) => i.id === id)
  const j = idx + dir
  if (idx < 0 || j < 0 || j >= list.length) return
  const a = list[idx], b = list[j]
  // 交换 sort：两个 PATCH 即可（服务端写前整体校验兜底）
  try {
    await Promise.all([
      api.patch(`/admin/comfyui/instances/${a.id}`, { sort: b.sort }),
      api.patch(`/admin/comfyui/instances/${b.id}`, { sort: a.sort }),
    ])
    await load()
  } catch (e) { /* */ }
}

// ---------------------------------------------------------------- Tab2
function setMatrix(name, key, val) {
  if (matrix.value[name]) matrix.value[name] = { ...matrix.value[name], [key]: val }
}

async function saveMatrix() {
  if (!selected.value) return
  saving.value = true
  try {
    const only = wfNames.value.filter((n) => matrix.value[n]?.only)
    const excl = wfNames.value.filter((n) => matrix.value[n]?.excl)
    await api.put(`/admin/comfyui/instances/${selected.value.id}/rules`,
      { only, exclude: excl })
    // 全局白名单：名字级按矩阵重建 + 保留非名字条目（通配符原样）
    const nameSet = new Set(wfNames.value)
    const kept = whitelist.value.filter((e) => !nameSet.has(e.pattern))
    const toggled = wfNames.value.filter((n) => matrix.value[n]?.wl)
      .map((n) => ({ pattern: n, active: 1 }))
    const wlEntries = [...toggled, ...kept]
    await api.put('/admin/comfyui/whitelist', { entries: wlEntries })
    ElMessage.success('已保存（规则 + 白名单即时生效）')
    await load()
  } catch (e) { /* */ } finally { saving.value = false }
}

// ---------------------------------------------------------------- Tab3
async function setDefault() {
  if (!defaultDraft.value) return ElMessage.warning('请选择默认实例')
  try {
    await api.put('/admin/comfyui/default', { instance: defaultDraft.value })
    ElMessage.success('默认实例已切换')
    await load()
  } catch (e) { /* 拦截器已提示 */ }
}

async function saveAdvanced() {
  saving.value = true
  try {
    const prune_modes = {}
    for (const r of pruneDraft.value) {
      const k = (r.key || '').trim()
      if (k) prune_modes[k] = r.mode
    }
    await api.put('/admin/comfyui/advanced', {
      pending: Number(advDraft.value.pending),
      running: Number(advDraft.value.running),
      prune_modes,
    })
    ElMessage.success('已保存')
    await load()
  } catch (e) { /* */ } finally { saving.value = false }
}
</script>

<template>
  <div class="comfyui-page" v-loading="loading">
    <div class="cols">
      <!-- 左栏：实例卡片 -->
      <div class="card left">
        <div class="card-title">实例（{{ instances.length }}）</div>
        <div
          v-for="(inst, idx) in sortedInstances"
          :key="inst.id"
          class="inst-card"
          :class="{ active: selected && selected.id === inst.id }"
          @click="selectInstance(inst)"
        >
          <div class="inst-head">
            <span class="inst-name">
              <el-icon v-if="inst.name === defaultName" class="star"><StarFilled /></el-icon>
              {{ inst.name }}
            </span>
            <el-tag :type="inst.active ? 'success' : 'info'" size="small">
              {{ inst.active ? '启用' : '禁用' }}
            </el-tag>
          </div>
          <div class="inst-url muted">{{ inst.url }}</div>
          <div class="inst-meta muted small">
            only {{ (inst.only || []).length }} · exclude {{ (inst.exclude || []).length }}
          </div>
          <div class="inst-actions" @click.stop>
            <el-button size="small" text :disabled="idx === 0" @click="move(inst.id, -1)">上移</el-button>
            <el-button size="small" text
              :disabled="idx === sortedInstances.length - 1"
              @click="move(inst.id, 1)">下移</el-button>
          </div>
        </div>
        <el-button type="primary" plain style="width: 100%" @click="createDialog = true">
          + 新建实例
        </el-button>
      </div>

      <!-- 右栏：Tab -->
      <div class="card right">
        <template v-if="selected">
          <el-tabs v-model="tab">
            <!-- Tab1 实例设置 -->
            <el-tab-pane label="实例设置" name="settings">
              <el-form label-width="90px" style="max-width: 560px">
                <el-form-item label="实例名">
                  <code class="mono">{{ selected.name }}</code>
                  <el-tag v-if="selected.name === defaultName" type="warning" size="small"
                    style="margin-left: 8px">默认</el-tag>
                </el-form-item>
                <el-form-item label="URL">
                  <el-input v-model="urlDraft" placeholder="http://host:port（去尾斜杠）" />
                </el-form-item>
                <el-form-item label="密码">
                  <el-input v-model="pwdDraft" type="password" show-password
                    placeholder="实例登录密码（明文存储，仅 admin 可见）" />
                </el-form-item>
                <el-form-item label="启用">
                  <el-switch v-model="selected.active" :active-value="1" :inactive-value="0"
                    @change="toggleActive" />
                  <span class="muted small" style="margin-left: 8px">
                    禁用后不再路由/接收新任务，在途任务不受影响
                  </span>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="saving" @click="saveSettings">保存</el-button>
                  <el-button type="danger" plain @click="removeInstance">删除实例</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- Tab2 勾选矩阵 -->
            <el-tab-pane label="工作流勾选" name="matrix">
              <div class="toolbar">
                <el-button type="primary" :loading="saving" @click="saveMatrix">保存整表</el-button>
                <span class="muted">
                  白名单列改动全局生效；only/exclude 列仅对本实例
                  （{{ wfNames.length }} 个工作流）
                </span>
              </div>
              <el-table :data="wfNames.map((n) => ({ name: n, ...matrix[n] }))"
                size="small" stripe max-height="520" empty-text="没有工作流">
                <el-table-column prop="name" label="工作流" min-width="240">
                  <template #default="{ row }"><code class="mono">{{ row.name }}</code></template>
                </el-table-column>
                <el-table-column label="全局白名单" width="110" align="center">
                  <template #default="{ row }">
                    <el-checkbox :model-value="row.wl"
                      @change="(v) => setMatrix(row.name, 'wl', v)" />
                  </template>
                </el-table-column>
                <el-table-column label="本实例 only" width="110" align="center">
                  <template #default="{ row }">
                    <el-checkbox :model-value="row.only"
                      @change="(v) => setMatrix(row.name, 'only', v)" />
                  </template>
                </el-table-column>
                <el-table-column label="本实例 exclude" width="110" align="center">
                  <template #default="{ row }">
                    <el-checkbox :model-value="row.excl"
                      @change="(v) => setMatrix(row.name, 'excl', v)" />
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>
        <div v-else class="muted empty-tip">请选择或新建实例</div>

        <!-- Tab3 高级：专区级（不随实例） -->
        <el-divider />
        <h3 class="sec-title">高级设置（全实例）</h3>
        <el-form label-width="110px" style="max-width: 640px">
          <el-form-item label="默认实例">
            <el-select v-model="defaultDraft" style="width: 260px">
              <el-option v-for="i in instances" :key="i.id" :label="i.name"
                :value="i.name" :disabled="!i.active"
                :title="i.active ? '' : '已禁用实例不能设为默认'" />
            </el-select>
          </el-form-item>
          <el-form-item label="路由权重">
            <div style="display: flex; gap: 12px; align-items: center">
              <el-input-number v-model="advDraft.pending" :min="0" :step="0.1"
                :precision="2" :controls="false" style="width: 140px" />
              <span class="muted small">× pending</span>
              <el-input-number v-model="advDraft.running" :min="0" :step="0.1"
                :precision="2" :controls="false" style="width: 140px" />
              <span class="muted small">× running（分越低越优先）</span>
            </div>
          </el-form-item>
          <el-form-item label="切换默认">
            <el-button type="primary" plain
              :disabled="defaultDraft === advanced.default_instance"
              @click="setDefault">设为默认</el-button>
          </el-form-item>
          <el-form-item label="手术制度">
            <div class="prune-list">
              <div v-for="(row, i) in pruneDraft" :key="i" class="prune-row">
                <el-input v-model="row.key" placeholder="工作流名（fnmatch）" style="width: 280px" />
                <el-select v-model="row.mode" style="width: 160px">
                  <el-option label="image_edit（首图必传）" value="image_edit" />
                  <el-option label="multi_ref（混合多参考）" value="multi_ref" />
                </el-select>
                <el-button size="small" text type="danger" @click="pruneDraft.splice(i, 1)">移除</el-button>
              </div>
              <el-button size="small" @click="pruneDraft.push({ key: '', mode: 'image_edit' })">
                + 添加制度
              </el-button>
            </div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveAdvanced">保存高级设置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>

    <!-- 新建实例 -->
    <el-dialog v-model="createDialog" title="新建实例" width="480px">
      <el-form label-width="70px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="如 U7P-0" />
        </el-form-item>
        <el-form-item label="URL" required>
          <el-input v-model="createForm.url" placeholder="http://host:port" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createInstance">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.comfyui-page { min-height: 60vh; }
.cols { display: grid; grid-template-columns: 300px 1fr; gap: 14px; align-items: start; }
@media (max-width: 767px) { .cols { grid-template-columns: 1fr; } }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px; }
.card-title { font-weight: 700; margin-bottom: 10px; }
.right { min-height: 420px; }
.inst-card {
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
  margin-bottom: 10px; cursor: pointer; transition: border-color .15s;
}
.inst-card:hover { border-color: var(--el-color-primary, #409eff); }
.inst-card.active { border-color: var(--el-color-primary, #409eff);
  box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset; }
.inst-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.inst-name { font-weight: 600; display: inline-flex; align-items: center; gap: 4px; }
.star { color: #e6a23c; }
.inst-url { margin-top: 4px; font-size: 12px; word-break: break-all; }
.inst-meta { font-size: 12px; margin-top: 2px; }
.inst-actions { margin-top: 4px; }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
.muted { color: var(--el-text-color-secondary, #909399); }
.small { font-size: 12px; }
.empty-tip { padding: 60px 0; text-align: center; }
.sec-title { font-size: 15px; margin: 6px 0 14px; }
.prune-list { display: flex; flex-direction: column; gap: 8px; }
.prune-row { display: flex; gap: 8px; align-items: center; }
</style>
