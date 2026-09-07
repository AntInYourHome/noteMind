<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { setUser } from '../store'

const router = useRouter()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const auth = ref({ mode: 'mixed', providers: [] })

onMounted(async () => {
  try {
    const { data } = await api.get('/auth/providers')
    auth.value = data
  } catch {
    /* 按本地密码登录 */
  }
})

const showPassword = computed(() => auth.value.mode !== 'oauth')

function oauthLogin(name) {
  location.href = `/api/auth/oauth/${name}/login?next=/admin/users&panel=admin`
}

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', { ...form, panel: 'admin' })
    localStorage.setItem('token', data.token)
    setUser(data.user)
    router.push('/admin/users')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card">
      <h2 style="margin-bottom: 24px; text-align: center">⚙️ 管理面登录</h2>

      <el-button
        v-for="p in auth.providers"
        :key="p.name"
        type="success"
        size="large"
        style="width: 100%; margin-bottom: 12px"
        @click="oauthLogin(p.name)"
      >
        🔐 {{ p.title }}
      </el-button>

      <template v-if="showPassword">
        <el-divider v-if="auth.providers.length" style="margin: 8px 0">
          <span style="color: #c0c4cc; font-size: 12px">或使用管理员账号</span>
        </el-divider>
        <el-form @keyup.enter="submit">
          <el-form-item>
            <el-input v-model="form.username" placeholder="管理员账号" size="large" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
          </el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
            登 录
          </el-button>
        </el-form>
      </template>
      <div class="tip">仅管理员账号可登录管理面</div>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
}
.card { width: 380px; }
.tip { margin-top: 12px; text-align: center; color: #909399; font-size: 13px; }
</style>
