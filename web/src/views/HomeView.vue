<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { store } from '../store'
import api from '../api'

const router = useRouter()
const tools = ref([])
const usageTool = ref(null)

onMounted(async () => {
  const { data } = await api.get('/tools')
  tools.value = data
})

function open(tool) {
  router.push(`/t/${tool.name}`)
}
</script>

<template>
  <div>
    <el-card shadow="never" class="banner">
      <h2>🧰 欢迎使用超级小工具</h2>
      <p>
        内部小工具平台：账号由管理员开通，左侧菜单进入各工具。
        <template v-if="store.user?.is_admin">
          管理员请走 <el-link @click="router.push('/admin/users')">管理面</el-link> 管理用户、查看统计与数据。
        </template>
        有任何改进想法？去「💬 改进意见」告诉我们。
      </p>
    </el-card>

    <el-row :gutter="14" style="margin-top: 14px">
      <el-col v-for="t in tools" :key="t.name" :span="8" style="margin-bottom: 14px">
        <el-card shadow="hover" class="tool-card">
          <div class="tool-head">
            <span class="tool-icon">{{ t.icon || '🧩' }}</span>
            <span class="tool-title">{{ t.title }}</span>
          </div>
          <p class="tool-desc">{{ t.desc || '暂无简介' }}</p>
          <div class="tool-foot">
            <el-button type="primary" size="small" @click="open(t)">打开</el-button>
            <el-button v-if="t.usage" size="small" @click="usageTool = t">用法说明</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="usageTool" :title="`${usageTool?.icon || ''} ${usageTool?.title} · 用法说明`" width="520px">
      <p class="usage">{{ usageTool?.usage }}</p>
      <template #footer>
        <el-button @click="usageTool = null">关闭</el-button>
        <el-button type="primary" @click="open(usageTool)">立即打开</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.banner h2 { margin: 0 0 8px; color: #303133; }
.banner p { color: #606266; line-height: 1.8; margin: 0; }
.tool-card { height: 100%; }
.tool-head { display: flex; align-items: center; gap: 8px; }
.tool-icon { font-size: 26px; }
.tool-title { font-size: 16px; font-weight: 600; color: #303133; }
.tool-desc { color: #606266; font-size: 13px; line-height: 1.7; min-height: 46px; margin: 10px 0 4px; }
.tool-foot { display: flex; gap: 8px; }
.usage { white-space: pre-line; color: #303133; line-height: 1.9; margin: 0; }
</style>
