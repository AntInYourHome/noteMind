<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

// 工具与表选择
const tools = ref([])
const tool = ref('')
const tables = ref({})
const table = ref('')

// 当前表数据
const columns = ref([])
const items = ref([])
const total = ref(0)
const query = reactive({ skip: 0, limit: 50, keyword: '' })
const loading = ref(false)

// 行编辑对话框
const dialog = ref(false)
const editingId = ref(null)
const form = ref({})

const tableOptions = computed(() =>
  Object.entries(tables.value).map(([name, label]) => ({ name, label: label === name ? name : `${label}（${name}）` }))
)

async function loadTools() {
  const { data } = await api.get('/tools')
  tools.value = data.filter((t) => Object.keys(t.tables || {}).length > 0)
  if (tools.value.length) selectTool(tools.value[0].name)
}

function selectTool(name) {
  tool.value = name
  tables.value = tools.value.find((t) => t.name === name)?.tables || {}
  table.value = Object.keys(tables.value)[0] || ''
}

async function loadRows() {
  if (!tool.value || !table.value) return
  loading.value = true
  try {
    const { data } = await api.get(`/admin/data/${tool.value}/${table.value}`, { params: query })
    columns.value = data.columns
    items.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function search() {
  query.skip = 0
  loadRows()
}

function pageChange(page) {
  query.skip = (page - 1) * query.limit
  loadRows()
}

function openCreate() {
  editingId.value = null
  form.value = {}
  dialog.value = true
}

function openEdit(row) {
  editingId.value = row[pkName.value]
  form.value = { ...row }
  dialog.value = true
}

const pkName = computed(() => columns.value.find((c) => c.pk)?.name || 'id')
const editableColumns = computed(() => columns.value.filter((c) => !c.pk))

async function save() {
  try {
    if (editingId.value) {
      await api.put(`/admin/data/${tool.value}/${table.value}/${editingId.value}`, { data: form.value })
    } else {
      await api.post(`/admin/data/${tool.value}/${table.value}`, { data: form.value })
    }
    dialog.value = false
    loadRows()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除该行（${pkName.value}=${row[pkName.value]}）？`, '提示', { type: 'warning' })
  try {
    await api.delete(`/admin/data/${tool.value}/${table.value}/${row[pkName.value]}`)
    loadRows()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

// 导入
const fileList = ref([])
const importing = ref(false)
async function doImport() {
  const file = fileList.value?.[0]?.raw
  if (!file) return ElMessage.warning('请先选择文件')
  const fd = new FormData()
  fd.append('file', file)
  importing.value = true
  try {
    const { data } = await api.post(`/admin/data/${tool.value}/${table.value}/import`, fd)
    ElMessage.success(`导入完成：新增 ${data.inserted} 条，跳过 ${data.skipped} 条（共 ${data.total_rows} 行）`)
    fileList.value = []
    loadRows()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

// 导出
const exporting = ref(false)
async function doExport(format) {
  exporting.value = true
  try {
    const res = await api.get(`/admin/data/${tool.value}/${table.value}/export`, {
      params: { format },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `${table.value}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

watch(table, () => {
  query.skip = 0
  query.keyword = ''
  loadRows()
})
onMounted(loadTools)
</script>

<template>
  <el-card>
    <template #header>
      🗄 数据管理（任意工具表：增删改查 / 导入 / 导出）
    </template>

    <div style="display: flex; gap: 12px; margin-bottom: 12px; align-items: center">
      <el-select v-model="tool" style="width: 220px" @change="selectTool">
        <el-option v-for="t in tools" :key="t.name" :label="t.title" :value="t.name" />
      </el-select>
      <el-select v-model="table" style="width: 240px" placeholder="选择数据表">
        <el-option v-for="t in tableOptions" :key="t.name" :label="t.label" :value="t.name" />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="搜索文本字段"
        clearable
        style="width: 220px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button @click="search">搜索</el-button>
      <div style="flex: 1" />
      <el-upload
        v-model:file-list="fileList"
        :auto-upload="false"
        :limit="1"
        accept=".csv,.xlsx"
        :show-file-list="false"
      >
        <el-button :loading="importing">📥 导入 CSV/XLSX</el-button>
      </el-upload>
      <el-button :loading="exporting" @click="doExport('csv')">📤 导出CSV</el-button>
      <el-button :loading="exporting" @click="doExport('xlsx')">📤 导出XLSX</el-button>
      <el-button type="primary" @click="openCreate">＋ 新增</el-button>
    </div>

    <el-table v-loading="loading" :data="items" stripe size="small">
      <el-table-column v-for="c in columns" :key="c.name" :label="c.name" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="c.kind === 'boolean'">
            <el-tag :type="row[c.name] ? 'success' : 'info'" size="small">{{ row[c.name] ? '是' : '否' }}</el-tag>
          </template>
          <template v-else>{{ row[c.name] ?? '—' }}</template>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      style="margin-top: 14px; justify-content: flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="query.limit"
      :current-page="query.skip / query.limit + 1"
      @current-change="pageChange"
    />

    <el-dialog v-model="dialog" :title="editingId ? '编辑行' : `新增行（${table}）`" width="560px">
      <el-form label-width="130px">
        <el-form-item v-for="c in editableColumns" :key="c.name" :label="c.name" :required="c.required">
          <el-switch v-if="c.kind === 'boolean'" v-model="form[c.name]" />
          <el-input-number v-else-if="c.kind === 'integer'" v-model="form[c.name]" style="width: 200px" />
          <el-input-number v-else-if="c.kind === 'float'" v-model="form[c.name]" :precision="2" style="width: 200px" />
          <el-date-picker
            v-else-if="c.kind === 'datetime'"
            v-model="form[c.name]"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 220px"
          />
          <el-date-picker
            v-else-if="c.kind === 'date'"
            v-model="form[c.name]"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 220px"
          />
          <el-input
            v-else-if="c.kind === 'text'"
            v-model="form[c.name]"
            type="textarea"
            :rows="3"
          />
          <el-input v-else v-model="form[c.name]" :maxlength="c.max_length || undefined" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
