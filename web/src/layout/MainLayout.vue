<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { store, logout as clearAuth } from '../store'

const router = useRouter()
const tools = ref([])

onMounted(async () => {
  try {
    const { data } = await api.get('/tools')
    tools.value = data
  } catch (e) {
    /* 401 已由拦截器处理 */
  }
})

function logout() {
  clearAuth()
  router.push('/login')
}
</script>

<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" class="aside">
      <div class="logo">🧰 超级小工具</div>
      <el-menu router :default-active="$route.path" class="menu">
        <el-menu-item v-for="t in tools" :key="t.name" :index="`/t/${t.name}`">
          {{ t.title }}
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span />
        <span class="user">
          {{ store.user?.username }}
          <el-button link type="primary" @click="logout">退出登录</el-button>
        </span>
      </el-header>
      <el-main style="background: #f5f7fa">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.aside { background: #fff; border-right: 1px solid #e4e7ed; }
.logo { font-size: 18px; font-weight: 600; padding: 20px 16px; color: #303133; }
.menu { border-right: none; }
.header {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e4e7ed;
}
.user { color: #606266; }
</style>
