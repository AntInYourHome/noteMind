<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const loading = ref(false)
const fileList = ref([])
const text = ref('')
const result = ref(null)

const levelColors = {
  ERROR: 'danger', WARN: 'warning', INFO: 'primary',
  DEBUG: 'info', NOTICE: 'success', OTHER: 'info',
}

async function analyze() {
  const file = fileList.value?.[0]?.raw
  if (!file && !text.value.trim()) {
    ElMessage.warning('请选择日志文件或粘贴日志文本')
    return
  }
  loading.value = true
  try {
    let res
    if (file) {
      const fd = new FormData()
      fd.append('file', file)
      res = await api.post('/tools/log_parser/analyze', fd)
    } else {
      res = await api.post('/tools/log_parser/analyze', `text=${encodeURIComponent(text.value)}`, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
    }
    result.value = res.data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '解析失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-card>
    <template #header>📋 日志解析（支持 .log/.txt 等，最大 20MB）</template>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-upload v-model:file-list="fileList" drag :auto-upload="false" :limit="1">
          <div style="padding: 24px 0">拖拽日志文件到此处，或 <em>点击选择</em></div>
        </el-upload>
      </el-col>
      <el-col :span="14">
        <el-input
          v-model="text"
          type="textarea"
          :rows="6"
          placeholder="或在此粘贴日志文本（选择了文件时优先使用文件）"
        />
      </el-col>
    </el-row>
    <el-button type="primary" style="margin-top: 16px" :loading="loading" @click="analyze">
      开始解析
    </el-button>

    <template v-if="result">
      <el-divider />
      <el-row :gutter="12">
        <el-col :span="4"><el-statistic title="总行数" :value="result.total_lines" /></el-col>
        <el-col :span="4"><el-statistic title="ERROR" :value="result.levels.ERROR || 0" /></el-col>
        <el-col :span="4"><el-statistic title="WARN" :value="result.levels.WARN || 0" /></el-col>
        <el-col :span="4"><el-statistic title="INFO" :value="result.levels.INFO || 0" /></el-col>
        <el-col :span="8">
          <div class="ts">
            <div v-if="result.first_timestamp">起始：{{ result.first_timestamp }}</div>
            <div v-if="result.last_timestamp">结束：{{ result.last_timestamp }}</div>
          </div>
        </el-col>
      </el-row>

      <div style="margin: 10px 0">
        <el-tag
          v-for="(count, lv) in result.levels"
          :key="lv"
          :type="levelColors[lv] || 'info'"
          style="margin-right: 8px"
        >{{ lv }}: {{ count }}</el-tag>
      </div>

      <h4>❌ 错误聚类（Top {{ result.error_groups.length }}）</h4>
      <el-table :data="result.error_groups" size="small" stripe>
        <el-table-column prop="count" label="次数" width="70" sortable />
        <el-table-column prop="first_line" label="首次行号" width="90" />
        <el-table-column prop="last_line" label="末次行号" width="90" />
        <el-table-column prop="sample" label="样本（数字/地址已归一化聚类）" show-overflow-tooltip />
      </el-table>

      <h4 style="margin-top: 16px">⚠️ 告警聚类（Top {{ result.warn_groups.length }}）</h4>
      <el-table :data="result.warn_groups" size="small" stripe>
        <el-table-column prop="count" label="次数" width="70" />
        <el-table-column prop="first_line" label="首次行号" width="90" />
        <el-table-column prop="last_line" label="末次行号" width="90" />
        <el-table-column prop="sample" label="样本" show-overflow-tooltip />
      </el-table>
    </template>
  </el-card>
</template>

<style scoped>
.ts { color: #909399; font-size: 13px; line-height: 1.8; }
h4 { margin: 16px 0 8px; color: #303133; }
</style>
