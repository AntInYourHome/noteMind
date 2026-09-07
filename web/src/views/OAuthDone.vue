<script setup>
// OAuth 回调落点：后端 302 到 /oauth/done?token=...&next=...（或 ?error=...）
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import { setUser } from '../store'

const route = useRoute()
const router = useRouter()
const error = ref('')
const detail = ref('')

onMounted(async () => {
  const token = route.query.token
  const next = String(route.query.next || '/')
  if (token) {
    localStorage.setItem('token', token)
    try {
      const { data } = await api.get('/auth/me')
      setUser(data)
      router.replace(next.startsWith('/') && !next.startsWith('//') ? next : '/')
      return
    } catch {
      error.value = '会话建立失败，请重新登录'
    }
  } else {
    error.value = String(route.query.error || '未知错误')
    detail.value = String(route.query.detail || '')
  }
})
</script>

<template>
  <div class="page">
    <el-card class="card">
      <template v-if="!error">
        <div class="spinner" />
        <p>统一认证完成，正在进入平台…</p>
      </template>
      <template v-else>
        <h3>❌ 统一认证失败</h3>
        <p class="err">{{ error }}</p>
        <p v-if="detail" class="detail">{{ detail }}</p>
        <div style="display: flex; gap: 10px; justify-content: center">
          <el-button type="primary" @click="$router.push('/login')">返回业务面登录</el-button>
          <el-button @click="$router.push('/admin/login')">管理面登录</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.page { height: 100vh; display: flex; align-items: center; justify-content: center; background: #f5f7fa; }
.card { width: 400px; text-align: center; padding: 8px 0; }
.err { color: #f56c6c; font-weight: 600; }
.detail { color: #909399; font-size: 13px; word-break: break-all; }
.spinner {
  width: 32px; height: 32px; margin: 8px auto 12px;
  border: 3px solid #dcdfe6; border-top-color: #409eff; border-radius: 50%;
  animation: rot 0.8s linear infinite;
}
@keyframes rot { to { transform: rotate(360deg); } }
</style>
