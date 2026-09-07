<script setup>
import { useRouter } from 'vue-router'
import { store, logout as clearAuth } from '../store'

const router = useRouter()

function logout() {
  clearAuth()
  router.push('/admin/login')
}
</script>

<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" class="aside">
      <div class="logo">⚙️ 管理面</div>
      <el-menu
        router
        :default-active="$route.path"
        class="menu"
        background-color="#001529"
        text-color="#a6adb4"
        active-text-color="#fff"
      >
        <el-menu-item index="/admin/stats">📊 使用统计</el-menu-item>
        <el-menu-item index="/admin/data">🗄 数据管理</el-menu-item>
        <el-menu-item index="/admin/users">👥 用户管理</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="title">超级小工具 · 管理面</span>
        <span class="user">
          <el-link style="margin-right: 14px" @click="router.push('/')">返回业务面</el-link>
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
.aside { background: #001529; }
.logo { font-size: 18px; font-weight: 600; padding: 20px 16px; color: #fff; }
.menu { border-right: none; }
.header {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e4e7ed;
}
.title { font-weight: 600; color: #303133; }
.user { color: #606266; }
</style>
