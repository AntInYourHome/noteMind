<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

const items = ref([])
const total = ref(0)
const query = reactive({ skip: 0, limit: 20, keyword: '' })
const dialog = ref(false)
const editingId = ref(null)
const form = reactive({ title: '', content: '' })

async function load() {
  const { data } = await api.get('/tools/notes', { params: query })
  items.value = data.items
  total.value = data.total
}

function search() {
  query.skip = 0
  load()
}

function openCreate() {
  editingId.value = null
  form.title = ''
  form.content = ''
  dialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.title = row.title
  form.content = row.content
  dialog.value = true
}

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('标题不能为空')
    return
  }
  if (editingId.value) {
    await api.put(`/tools/notes/${editingId.value}`, form)
  } else {
    await api.post('/tools/notes', form)
  }
  dialog.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除「${row.title}」？`, '提示', { type: 'warning' })
  await api.delete(`/tools/notes/${row.id}`)
  load()
}

function pageChange(page) {
  query.skip = (page - 1) * query.limit
  load()
}

onMounted(load)
</script>

<template>
  <el-card>
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
      <el-input
        v-model="query.keyword"
        placeholder="搜索标题 / 内容"
        clearable
        style="width: 300px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="openCreate">新增</el-button>
    </div>

    <el-table :data="items" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      style="margin-top: 16px; justify-content: flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="query.limit"
      :current-page="query.skip / query.limit + 1"
      @current-change="pageChange"
    />

    <el-dialog v-model="dialog" :title="editingId ? '编辑' : '新增'" width="520px">
      <el-form label-width="60px">
        <el-form-item label="标题">
          <el-input v-model="form.title" maxlength="200" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
