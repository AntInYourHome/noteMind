import { createRouter, createWebHistory } from 'vue-router'
import { registry } from './modules/registry'
import AdminLayout from './layout/AdminLayout.vue'
import MainLayout from './layout/MainLayout.vue'

const names = Object.keys(registry)

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 业务面：工具门户
    { path: '/login', component: () => import('./views/Login.vue') },
    // OAuth 回调落点（公开路由，拿到 token 后再跳目标页）
    { path: '/oauth/done', component: () => import('./views/OAuthDone.vue') },
    {
      path: '/',
      component: MainLayout,
      children: [
        ...names.map((name) => ({ path: `t/${name}`, component: registry[name] })),
        { path: '', redirect: () => (names[0] ? `/t/${names[0]}` : '/login') },
      ],
    },
    // 管理面：独立入口、独立登录，仅管理员
    { path: '/admin/login', component: () => import('./views/AdminLogin.vue') },
    {
      path: '/admin',
      component: AdminLayout,
      children: [
        { path: 'stats', component: () => import('./views/AdminStats.vue') },
        { path: 'data', component: () => import('./views/AdminData.vue') },
        { path: 'users', component: () => import('./views/AdminUsers.vue') },
        { path: '', redirect: '/admin/stats' },
      ],
    },
    { path: '/:pathMatch(.*)*', component: () => import('./views/NotFound.vue') },
  ],
})

const isAdminPath = (p) => p === '/admin' || p.startsWith('/admin')

router.beforeEach((to) => {
  // OAuth 回调页本身放行（它自己处理 token/错误）
  if (to.path === '/oauth/done') return true
  const hasToken = !!localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')

  // 已在登录页本身：直接放行，防止重定向到相同路径造成无限循环（白屏）
  if (to.path === '/admin/login') {
    return hasToken && user?.is_admin ? '/admin/users' : true
  }
  if (to.path === '/login') {
    return hasToken ? '/' : true
  }

  if (!hasToken) {
    return isAdminPath(to.path) ? '/admin/login' : '/login'
  }
  if (isAdminPath(to.path) && !user?.is_admin) {
    return '/admin/login'
  }
})

export default router
