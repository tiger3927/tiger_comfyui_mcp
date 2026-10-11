<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../lib/api'

const tokens = ref([])
const dialog = ref(false)
const form = ref({ name: '', credit_limit: 0, expires_at: '' })
const newToken = ref('')
const showPlain = ref(false)

async function load() {
  try {
    const d = await api.get('/me/tokens')
    tokens.value = d.tokens || []
  } catch (e) { /* ignore */ }
}
onMounted(load)

function openDialog() {
  form.value = { name: '', credit_limit: 0, expires_at: '' }
  dialog.value = true
}

async function create() {
  if (!form.value.name.trim()) return ElMessage.warning('请给 API Key 起名')
  if (Number(form.value.credit_limit) === 0) {
    try {
      await ElMessageBox.confirm(
        '上限设为 0 = 该 API Key 无积分上限，用多少扣多少，确定要无上限吗？',
        '无上限警示',
        { confirmButtonText: '确认无上限', cancelButtonText: '再想想', type: 'warning' },
      )
    } catch {
      return
    }
  }
  try {
    const d = await api.post('/me/tokens', {
      name: form.value.name.trim(),
      credit_limit: Number(form.value.credit_limit) || 0,
      expires_at: form.value.expires_at || null,
    })
    dialog.value = false
    newToken.value = d.token
    showPlain.value = true
    load()
  } catch (e) { /* ignore */ }
}

async function toggle(row) {
  try {
    await api.patch(`/me/tokens/${row.id}`, { disabled: row.disabled ? 0 : 1 })
    ElMessage.success(row.disabled ? '已启用' : '已停用（后续提交将被拒）')
    load()
  } catch (e) { /* ignore */ }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`删除 API Key「${row.name}」？近 7 天有任务则无法删除。`, '确认删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.delete(`/me/tokens/${row.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) { /* ignore */ }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(newToken.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

// ---------------- MCP 客户端配置 ----------------
const mcpDialog = ref(false)
const mcpRow = ref(null)
const mcpBase = ref('')

function openMcp(row) {
  mcpRow.value = row
  if (!mcpBase.value) mcpBase.value = window.location.origin
  mcpDialog.value = true
}

// baseURL 来处：默认当前访问地址 origin（生产 MCP 与门户同源）；可手动改（dev/反代/不同端口）
const mcpUrl = computed(() => {
  const b = (mcpBase.value || '').trim().replace(/\/+$/, '')
  return b ? `${b}/mcp/` : 'http://<host>:<port>/mcp/'
})

const mcpJson = computed(() => {
  const key = (mcpRow.value?.token_plain || '').trim()
  const cfg = {
    mcpServers: {
      'tiger-comfyui-mcp': {
        url: mcpUrl.value,
        headers: { Authorization: `Bearer ${key || '<你的 API Key>'}` },
        disabled: false,
      },
    },
  }
  return JSON.stringify(cfg, null, 2)
})

async function copyText(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

const fmt = (v) => Number(v || 0).toLocaleString()
</script>

<template>
  <div class="card">
    <div class="card-head">
      <h3 class="card-title">API Key 管理</h3>
      <el-button type="primary" size="small" @click="openDialog">创建 API Key</el-button>
    </div>
    <p class="muted mb16">把 API Key 配到 MCP 客户端的 <code>Authorization: Bearer</code>，之后提交的任务自动归属计费。</p>
    <el-table :data="tokens" empty-text="还没有 API Key，点上方「创建 API Key」按钮">
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column label="前缀" min-width="130">
        <template #default="{ row }"><code>{{ row.token_prefix }}…</code></template>
      </el-table-column>
      <el-table-column label="上限">
        <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.credit_limit) : '无上限' }}</template>
      </el-table-column>
      <el-table-column label="已用"><template #default="{ row }">{{ fmt(row.used) }}</template></el-table-column>
      <el-table-column label="剩余可用">
        <template #default="{ row }">{{ row.credit_limit > 0 ? fmt(row.remaining) : '—' }}</template>
      </el-table-column>
      <el-table-column label="状态">
        <template #default="{ row }">
          <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '停用' : '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="235">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click="openMcp(row)">MCP 配置</el-button>
          <el-button size="small" :type="row.disabled ? 'success' : 'warning'" @click="toggle(row)">
            {{ row.disabled ? '启用' : '停用' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="dialog" title="创建 API Key" width="440px">
    <el-form :model="form" label-width="90px">
      <el-form-item label="名称">
        <el-input v-model="form.name" placeholder="如：生产环境 / 测试" />
      </el-form-item>
      <el-form-item label="积分上限">
        <el-input-number v-model="form.credit_limit" :min="0" :step="100" :precision="0" />
        <span class="muted" style="margin-left: 8px">0 = 无上限</span>
      </el-form-item>
      <el-form-item label="过期时间">
        <el-date-picker
          v-model="form.expires_at" type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="可选" style="width: 100%"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" @click="create">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="showPlain" title="API Key 已创建（明文仅显示一次）" width="560px" :close-on-click-modal="false">
    <el-alert
      title="请立即复制保存，关闭后将无法再次查看完整 API Key（只能看前缀）。"
      type="warning" :closable="false" show-icon
    />
    <div class="plain-box"><code class="plain-text">{{ newToken }}</code></div>
    <p class="muted mt8">配到 MCP 客户端：<code>Authorization: Bearer {{ newToken }}</code></p>
    <template #footer>
      <el-button @click="copy">复制到剪贴板</el-button>
      <el-button type="primary" @click="showPlain = false">我已保存，关闭</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="mcpDialog" :title="`MCP 配置 - ${mcpRow?.name || ''}`" width="600px">
    <el-form label-width="100px">
      <el-form-item label="API Key">
        <div class="mcp-key-box" v-if="mcpRow?.token_plain">
          <code class="mcp-key">{{ mcpRow.token_plain }}</code>
          <el-button size="small" @click="copyText(mcpRow.token_plain)">复制</el-button>
        </div>
        <div class="muted" v-else>该密钥创建早于明文存储功能，无明文可显示；请新建一个 API Key 后再配置。</div>
      </el-form-item>
      <el-form-item label="服务地址">
        <el-input v-model="mcpBase" placeholder="http://host:port（不含 /mcp/）" />
      </el-form-item>
      <el-form-item label="MCP 配置">
        <pre class="mcp-json">{{ mcpJson }}</pre>
      </el-form-item>
    </el-form>
    <p class="muted mcp-tip">
      服务地址默认取当前访问地址（window.location.origin）；生产环境 MCP 与门户同源无需修改，本机开发 / 反向代理 / 不同端口请改为 MCP 服务实际地址。适用于 Claude / Cursor / Cline 等支持远程 MCP（Streamable HTTP）的客户端，写入 mcpServers 即可。
    </p>
    <template #footer>
      <el-button @click="mcpDialog = false">关闭</el-button>
      <el-button type="primary" @click="copyText(mcpJson)">复制 JSON</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-title { margin: 0; font-size: 16px; }
code { background: rgba(128,128,128,0.15); padding: 2px 6px; border-radius: 4px; }
.plain-box { background: rgba(128,128,128,0.1); border-radius: var(--radius-sm); padding: 12px; margin-top: 12px; }
.plain-text { word-break: break-all; font-size: 13px; }
.mcp-key-box { display: flex; gap: 8px; align-items: center; width: 100%; }
.mcp-key { flex: 1; word-break: break-all; background: rgba(128,128,128,0.12); padding: 8px; border-radius: var(--radius-sm); font-size: 13px; }
.mcp-json { margin: 0; padding: 12px; background: rgba(128,128,128,0.12); border-radius: var(--radius-sm); font-size: 13px; white-space: pre; overflow: auto; max-height: 240px; }
.mcp-tip { line-height: 1.5; margin: 8px 0 0; }
</style>
