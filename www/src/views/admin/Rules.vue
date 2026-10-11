<script setup>
import { onMounted, ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../lib/api'

const rules = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null) // null=新建，否则 rule 对象

const empty = () => ({
  pattern: '', media: 'image', price_per_mp: 0, price_per_char: 0, flat_price: 0,
  fps: 0, width_param: '', height_param: '', seconds_param: '', char_param: '',
  default_width: null, default_height: null, active: 1, remark: '',
})
const form = reactive(empty())

const mediaOpts = [
  { label: '图片（按像素）', value: 'image' },
  { label: '视频（按秒/fps）', value: 'video' },
  { label: '文本（按字数）', value: 'text' },
  { label: '固定价', value: 'flat' },
]

async function load() {
  loading.value = true
  try {
    const d = await api.get('/admin/rules')
    rules.value = d.rules || []
  } catch (e) { /* 拦截器已提示 */ } finally { loading.value = false }
}
onMounted(load)

function openCreate() {
  editing.value = null
  Object.assign(form, empty())
  dialog.value = true
}
function openEdit(r) {
  editing.value = r
  Object.assign(form, empty(), r)
  dialog.value = true
}
async function save() {
  if (!form.pattern) return ElMessage.warning('工作流匹配（pattern）必填')
  saving.value = true
  try {
    const payload = {
      ...form,
      price_per_mp: Number(form.price_per_mp) || 0,
      price_per_char: Number(form.price_per_char) || 0,
      flat_price: Number(form.flat_price) || 0,
      fps: Number(form.fps) || 0,
      default_width: form.default_width ? Number(form.default_width) : null,
      default_height: form.default_height ? Number(form.default_height) : null,
      width_param: form.width_param || null,
      height_param: form.height_param || null,
      seconds_param: form.seconds_param || null,
      char_param: form.char_param || null,
    }
    if (editing.value) await api.patch(`/admin/rules/${editing.value.id}`, payload)
    else await api.post('/admin/rules', payload)
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } catch (e) { /* */ } finally { saving.value = false }
}
</script>

<template>
  <div class="card">
    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新建规则</el-button>
      <el-button :loading="loading" @click="load">刷新</el-button>
      <span class="muted">一行一个工作流，按产物计价（§3.1）</span>
    </div>
    <el-table :data="rules" v-loading="loading" empty-text="没有计费规则" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="pattern" label="工作流匹配" min-width="160">
        <template #default="{ row }"><code class="mono">{{ row.pattern }}</code></template>
      </el-table-column>
      <el-table-column prop="media" label="类型" width="90" />
      <el-table-column label="每MP" width="90">
        <template #default="{ row }">{{ row.price_per_mp || 0 }}</template>
      </el-table-column>
      <el-table-column label="每字" width="90">
        <template #default="{ row }">{{ row.price_per_char || 0 }}</template>
      </el-table-column>
      <el-table-column label="固定价" width="90">
        <template #default="{ row }">{{ row.flat_price || 0 }}</template>
      </el-table-column>
      <el-table-column label="fps" width="70">
        <template #default="{ row }">{{ row.fps || 0 }}</template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="140">
        <template #default="{ row }"><span class="muted">{{ row.remark || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑规则' : '新建规则'" width="640px" top="8vh">
      <el-form :model="form" label-width="120px">
        <el-form-item label="工作流匹配" required>
          <el-input v-model="form.pattern" placeholder="fnmatch，如 video_* 或 hello" />
        </el-form-item>
        <el-form-item label="计价类型">
          <el-select v-model="form.media" style="width: 100%">
            <el-option v-for="m in mediaOpts" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="每 MP 积分">
          <el-input-number v-model="form.price_per_mp" :min="0" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每字积分">
          <el-input-number v-model="form.price_per_char" :min="0" :step="0.01" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="固定价（积分）">
          <el-input-number v-model="form.flat_price" :min="0" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="fps">
          <el-input-number v-model="form.fps" :min="0" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="宽参数名">
          <el-input v-model="form.width_param" placeholder="如 INPUT_WIDTH_VALUE" />
        </el-form-item>
        <el-form-item label="高参数名">
          <el-input v-model="form.height_param" placeholder="如 INPUT_HEIGHT_VALUE" />
        </el-form-item>
        <el-form-item label="秒参数名">
          <el-input v-model="form.seconds_param" placeholder="如 INPUT_SECONDS_VALUE" />
        </el-form-item>
        <el-form-item label="字数参数名">
          <el-input v-model="form.char_param" placeholder="如 INPUT_PROMPT_TEXT" />
        </el-form-item>
        <el-form-item label="默认宽">
          <el-input-number v-model="form.default_width" :min="0" :step="1" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="默认高">
          <el-input-number v-model="form.default_height" :min="0" :step="1" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.active" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
.mono { background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }
</style>
