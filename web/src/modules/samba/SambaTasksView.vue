<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

const status = ref({ configured: false, connected: false, detail: '' })
const items = ref([])
const loading = ref(false)

const createDialog = ref(false)
const createForm = reactive({ name: '' })

const filesDialog = ref(false)
const currentTask = ref('')
const files = ref([])
const fileList = ref([])
const uploading = ref(false)

// 数据库状态记录
const events = ref([])
const eventTask = ref('')
const EVENT_LABELS = {
  created: '创建任务', upload: '上传', download: '下载',
  complete: '标记完成', undo_complete: '取消完成',
}

async function loadEvents() {
  const { data } = await api.get('/tools/samba/db/events', {
    params: { task: eventTask.value || undefined, limit: 100 },
  })
  events.value = data.items
}

async function load() {
  loading.value = true
  try {
    const [s, t] = await Promise.all([
      api.get('/tools/samba/status'),
      api.get('/tools/samba/tasks'),
    ])
    status.value = s.data
    items.value = t.data.items
    loadEvents()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function createTask() {
  if (!createForm.name.trim()) return ElMessage.warning('请输入任务名')
  try {
    await api.post('/tools/samba/tasks', { name: createForm.name.trim() })
    ElMessage.success(`任务 ${createForm.name} 已创建`)
    createDialog.value = false
    createForm.name = ''
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  }
}

async function openFiles(row) {
  currentTask.value = row.name
  fileList.value = []
  filesDialog.value = true
  await loadFiles()
}

async function loadFiles() {
  const { data } = await api.get(`/tools/samba/tasks/${encodeURIComponent(currentTask.value)}/files`)
  files.value = data.items
}

async function upload() {
  const file = fileList.value?.[0]?.raw
  if (!file) return ElMessage.warning('请先选择文件')
  const fd = new FormData()
  fd.append('file', file)
  uploading.value = true
  try {
    await api.post(`/tools/samba/tasks/${encodeURIComponent(currentTask.value)}/files`, fd)
    ElMessage.success('上传成功')
    fileList.value = []
    loadFiles()
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function download(row) {
  const res = await api.get(
    `/tools/samba/tasks/${encodeURIComponent(currentTask.value)}/download`,
    { params: { file: row.name }, responseType: 'blob' }
  )
  const url = URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = row.name
  a.click()
  URL.revokeObjectURL(url)
}

async function toggleDone(row) {
  if (row.done) {
    await ElMessageBox.confirm(`确定将「${row.name}」重新标记为未完成？`, '提示', { type: 'warning' })
    await api.delete(`/tools/samba/tasks/${encodeURIComponent(row.name)}/complete`)
  } else {
    await ElMessageBox.confirm(`确定将「${row.name}」标记为完成（写入 complete.txt）？`, '提示')
    await api.post(`/tools/samba/tasks/${encodeURIComponent(row.name)}/complete`)
  }
  load()
}

function fmtSize(n) {
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB'
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB'
  return n + ' B'
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>
      📂 Samba 任务目录
      <el-tag
        size="small"
        :type="status.connected ? 'success' : status.configured ? 'danger' : 'info'"
        style="margin-left: 10px"
      >
        {{ status.connected ? '已连接' : status.configured ? '连接失败' : '未配置' }}
      </el-tag>
      <el-tooltip v-if="status.detail && !status.connected" :content="status.detail" placement="top">
        <span style="color: #909399; font-size: 12px; margin-left: 6px">详情</span>
      </el-tooltip>
    </template>

    <div style="display: flex; gap: 10px; margin-bottom: 12px">
      <el-button type="primary" @click="createDialog = true">＋ 新建任务</el-button>
      <el-button @click="load">刷新</el-button>
      <span class="tip">任务目录下存在 complete.txt 即视为完成</span>
    </div>

    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="name" label="任务" min-width="180" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.done ? 'success' : 'warning'">{{ row.done ? '✔ 完成' : '进行中' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="files_count" label="文件数" width="80" />
      <el-table-column prop="complete_time" label="完成时间" width="170">
        <template #default="{ row }">{{ row.complete_time || '—' }}</template>
      </el-table-column>
      <el-table-column prop="mtime" label="更新时间" width="170" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openFiles(row)">文件</el-button>
          <el-button link :type="row.done ? 'warning' : 'success'" @click="toggleDone(row)">
            {{ row.done ? '取消完成' : '标记完成' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider />
    <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px">
      <h4 style="margin: 0">📖 任务状态记录（数据库留痕）</h4>
      <el-select v-model="eventTask" clearable placeholder="全部任务" style="width: 220px" @change="loadEvents">
        <el-option v-for="t in items" :key="t.name" :label="t.name" :value="t.name" />
      </el-select>
      <el-button @click="loadEvents">刷新</el-button>
    </div>
    <el-table :data="events" size="small" stripe>
      <el-table-column prop="created_at" label="时间" width="160" />
      <el-table-column prop="task_name" label="任务" min-width="150" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">{{ EVENT_LABELS[row.event] || row.event }}</template>
      </el-table-column>
      <el-table-column prop="file" label="文件" min-width="160">
        <template #default="{ row }">{{ row.file || '—' }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="110" />
    </el-table>
    <el-empty v-if="!events.length" description="暂无操作记录" :image-size="60" />

    <el-dialog v-model="createDialog" title="新建任务目录" width="420px">
      <el-input v-model="createForm.name" placeholder="任务名（不支持 / \ : * ? 等字符）" @keyup.enter="createTask" />
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" @click="createTask">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="filesDialog" :title="`任务「${currentTask}」的文件`" width="640px">
      <div style="display: flex; gap: 10px; margin-bottom: 10px">
        <el-upload v-model:file-list="fileList" :auto-upload="false" :limit="1" :show-file-list="true">
          <el-button :loading="uploading">选择文件</el-button>
        </el-upload>
        <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
      </div>
      <el-table :data="files" size="small" stripe>
        <el-table-column prop="name" label="文件名" min-width="220" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ fmtSize(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="mtime" label="修改时间" width="170" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="download(row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!files.length" description="暂无文件（complete.txt 不在此显示）" :image-size="60" />
    </el-dialog>
  </el-card>
</template>

<style scoped>
.tip { color: #909399; font-size: 13px; align-self: center; }
</style>
