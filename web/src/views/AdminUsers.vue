<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const items = ref([])
const total = ref(0)
const createDialog = ref(false)
const resetDialog = ref(false)
const createForm = reactive({ username: '', password: '', is_admin: false })
const resetTarget = ref(null)
const newPassword = ref('')

async function load() {
  const { data } = await api.get('/admin/users')
  items.value = data.items
  total.value = data.total
}

async function createUser() {
  if (!createForm.username || createForm.password.length < 6) {
    ElMessage.warning('请填写用户名（密码至少 6 位）')
    return
  }
  try {
    await api.post('/admin/users', createForm)
    ElMessage.success(`用户 ${createForm.username} 创建成功`)
    createDialog.value = false
    createForm.username = ''
    createForm.password = ''
    createForm.is_admin = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  }
}

async function toggleAdmin(row) {
  try {
    await api.put(`/admin/users/${row.id}`, { is_admin: !row.is_admin })
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

function openReset(row) {
  resetTarget.value = row
  newPassword.value = ''
  resetDialog.value = true
}

async function doReset() {
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  await api.put(`/admin/users/${resetTarget.value.id}/password`, {
    new_password: newPassword.value,
  })
  ElMessage.success(`已重置 ${resetTarget.value.username} 的密码`)
  resetDialog.value = false
}

async function removeUser(row) {
  await ElMessageBox.confirm(`确定删除用户「${row.username}」？`, '提示', { type: 'warning' })
  try {
    await api.delete(`/admin/users/${row.id}`)
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>👥 用户管理（共 {{ total }} 个账号）</template>

    <div style="margin-bottom: 12px">
      <el-button type="primary" @click="createDialog = true">新增用户</el-button>
    </div>

    <el-table :data="items" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="用户名" min-width="150">
        <template #default="{ row }">
          <div>{{ row.username }}</div>
          <div v-if="row.display_name || row.email" class="sub">
            {{ [row.display_name, row.email].filter(Boolean).join(' · ') }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag :type="row.is_admin ? 'danger' : 'info'">
            {{ row.is_admin ? '管理员' : '业务用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.oauth_provider" type="success" size="small">OAuth·{{ row.oauth_provider }}</el-tag>
          <el-tag v-else type="info" size="small">本地</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="!!row.oauth_provider" @click="openReset(row)">重置密码</el-button>
          <el-button link type="warning" @click="toggleAdmin(row)">
            {{ row.is_admin ? '撤销管理员' : '设为管理员' }}
          </el-button>
          <el-button link type="danger" @click="removeUser(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialog" title="新增用户" width="440px">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" placeholder="2-32 位字母/数字/下划线" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-switch v-model="createForm.is_admin" active-text="管理员" inactive-text="业务用户" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" @click="createUser">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetDialog" :title="`重置 ${resetTarget?.username} 的密码`" width="400px">
      <el-input v-model="newPassword" type="password" show-password placeholder="新密码（至少 6 位）" />
      <template #footer>
        <el-button @click="resetDialog = false">取消</el-button>
        <el-button type="primary" @click="doReset">确认重置</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.sub { font-size: 12px; color: #909399; }
</style>
