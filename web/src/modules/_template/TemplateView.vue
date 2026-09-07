<script setup>
// 新工具前端页面模板：复制本目录为 web/src/modules/<你的工具名>/，
// 然后在 web/src/modules/registry.js 注册一行：'<工具名>': () => import('./<工具名>/TemplateView.vue')
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

const items = ref([])
const total = ref(0)
const query = reactive({ skip: 0, limit: 20, keyword: '' })
const dialog = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', remark: '' })

async function load() {
  // 后端接口固定前缀 /tools/<工具名>
  const { data } = await api.get('/tools/<工具名>', { params: query })
  items.value = data.items
  total.value = data.total
}

function openCreate() {
  editingId.value = null
  form.name = ''
  form.remark = ''
  dialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.name = row.name
  form.remark = row.remark
  dialog.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('名称不能为空')
  if (editingId.value) await api.put(`/tools/<工具名>/${editingId.value}`, form)
  else await api.post('/tools/<工具名>', form)
  dialog.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除「${row.name}」？`, '提示', { type: 'warning' })
  await api.delete(`/tools/<工具名>/${row.id}`)
  load()
}

onMounted(load)
</script>

<template>
  <el-card>
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <el-input v-model="query.keyword" placeholder="搜索" clearable style="width: 300px" @keyup.enter="load" @clear="load" />
      <el-button type="primary" @click="openCreate">新增</el-button>
    </div>
    <el-table :data="items" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="remark" label="备注" min-width="240" show-overflow-tooltip />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top: 12px; justify-content: flex-end" layout="total, prev, pager, next"
      :total="total" :page-size="query.limit" @current-change="(p) => { query.skip = (p - 1) * query.limit; load() }" />
    <el-dialog v-model="dialog" :title="editingId ? '编辑' : '新增'" width="480px">
      <el-form label-width="70px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
