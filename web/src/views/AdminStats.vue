<script setup>
import { onMounted, ref } from 'vue'
import api from '../api'

const stats = ref(null)
const timer = ref(null)

async function load() {
  try {
    const { data } = await api.get('/admin/stats')
    stats.value = data
  } catch {
    /* 401 由拦截器处理 */
  }
}

function fmtUptime(sec) {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return d > 0 ? `${d}天${h}小时` : h > 0 ? `${h}小时${m}分` : `${m}分钟`
}

const maxRequests = () => Math.max(1, ...daily().map((x) => x.requests))
const daily = () => stats.value?.daily || []
const maxTool = () => Math.max(1, ...Object.values(stats.value?.per_tool || { x: 1 }))
const toolTitle = (name) => {
  const t = (stats.value?.tools || []).find?.((x) => x.name === name)
  return t ? t.title : name
}

onMounted(() => {
  load()
  timer.value = setInterval(load, 60000)  // 每分钟自动刷新
})
</script>

<template>
  <div v-if="stats" class="stats">
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="今日访问用户" :value="stats.overview.active_users_today" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="今日请求次数" :value="stats.overview.requests_today" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="今日错误(5xx)" :value="stats.overview.errors_today" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="总用户数" :value="stats.overview.total_users" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="15">
        <el-card shadow="never">
          <template #header>近 14 天使用量（柱：请求数，柱下数字：活跃用户）</template>
          <div class="bars">
            <div v-for="d in daily()" :key="d.date" class="bar-col">
              <div class="bar-count">{{ d.requests }}</div>
              <div class="bar-track">
                <div class="bar" :style="{ height: (d.requests / maxRequests()) * 100 + '%' }" />
              </div>
              <div class="bar-date">{{ d.date }}</div>
              <div class="bar-uv">{{ d.users }}人</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="9">
        <el-card shadow="never">
          <template #header>工具使用分布（近 14 天）</template>
          <div v-for="(count, name) in stats.per_tool" :key="name" class="tool-row">
            <span class="tool-name">{{ name }}</span>
            <div class="tool-track">
              <div class="tool-bar" :style="{ width: (count / maxTool()) * 100 + '%' }" />
            </div>
            <span class="tool-count">{{ count }}</span>
          </div>
          <el-empty v-if="!Object.keys(stats.per_tool).length" description="暂无工具访问记录" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="15">
        <el-card shadow="never">
          <template #header>最近访问</template>
          <el-table :data="stats.recent" size="small" stripe>
            <el-table-column prop="ts" label="时间" width="110" />
            <el-table-column prop="username" label="用户" width="100" />
            <el-table-column prop="path" label="接口" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <span :style="{ color: row.status >= 500 ? '#f56c6c' : row.status >= 400 ? '#e6a23c' : '#67c23a' }">
                  {{ row.status }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="duration_ms" label="耗时(ms)" width="80" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="9">
        <el-card shadow="never">
          <template #header>服务健康</template>
          <div class="health">
            <p><span class="dot ok" /> 数据库连接正常</p>
            <p>运行时长：{{ fmtUptime(stats.health.uptime_sec) }}</p>
            <p>已加载工具：{{ stats.health.tools }} 个</p>
            <p>日志保留：{{ stats.health.retention_days }} 天（自动老化清理）</p>
            <p>版本：v{{ stats.health.version }}</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.bars { display: flex; align-items: flex-end; gap: 4px; height: 200px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.bar-count { font-size: 11px; color: #909399; margin-bottom: 2px; }
.bar-track { width: 60%; height: 150px; display: flex; align-items: flex-end; background: #f5f7fa; border-radius: 3px 3px 0 0; }
.bar { width: 100%; background: linear-gradient(180deg, #79bbff, #409eff); border-radius: 3px 3px 0 0; min-height: 2px; }
.bar-date { font-size: 11px; color: #606266; margin-top: 4px; }
.bar-uv { font-size: 11px; color: #b0b3b8; }
.tool-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
.tool-name { width: 90px; font-size: 13px; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-track { flex: 1; height: 14px; background: #f5f7fa; border-radius: 7px; overflow: hidden; }
.tool-bar { height: 100%; background: linear-gradient(90deg, #b3e19d, #67c23a); border-radius: 7px; }
.tool-count { width: 46px; text-align: right; font-size: 12px; color: #606266; }
.health p { margin: 10px 0; color: #303133; font-size: 14px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.ok { background: #67c23a; }
</style>
