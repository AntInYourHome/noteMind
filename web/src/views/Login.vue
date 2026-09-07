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
    /* 接口不可用时按本地密码登录 */
  }
})

// mode=oauth 时隐藏密码表单，仅保留统一认证入口
const showPassword = computed(() => auth.value.mode !== 'oauth')

function oauthLogin(name) {
  location.href = `/api/auth/oauth/${name}/login?next=/`
}

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', form)
    localStorage.setItem('token', data.token)
    setUser(data.user)
    router.push('/')
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
      <h2 style="margin-bottom: 24px; text-align: center">🧰 超级小工具</h2>

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
          <span style="color: #c0c4cc; font-size: 12px">或使用账号密码</span>
        </el-divider>
        <el-form @keyup.enter="submit">
          <el-form-item>
            <el-input v-model="form.username" placeholder="用户名" size="large" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
          </el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
            登 录
          </el-button>
        </el-form>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.card { width: 380px; }
</style>
