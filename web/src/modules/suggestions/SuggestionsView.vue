<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const form = reactive({ content: '' })
const submitting = ref(false)
const items = ref([])
const total = ref(0)

// 与后端一致的白名单：中文、字母、数字、空白、常见中英文标点
const ALLOWED = /^[\u4e00-\u9fa5A-Za-z0-9 \s，。！？、：；“”‘’（）\-_,.!?;:()]+$/

async function load() {
  const { data } = await api.get('/tools/suggestions')
  items.value = data.items
  total.value = data.total
}

async function submit() {
  const content = form.content.trim()
  if (!content) return ElMessage.warning('内容不能为空')
  if (content.length > 100) return ElMessage.warning('最多 100 字')
  if (!ALLOWED.test(content)) return ElMessage.warning('包含不支持的字符：仅允许中文、字母、数字与常见标点')
  submitting.value = true
  try {
    await api.post('/tools/suggestions', { content })
    ElMessage.success('感谢反馈，已收到你的建议！')
    form.content = ''
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>💬 改进意见</template>

    <el-input
      v-model="form.content"
      type="textarea"
      :rows="3"
      maxlength="100"
      show-word-limit
      placeholder="说说你希望平台改进的地方（最多 100 字，仅支持中文、字母、数字与常见标点）"
    />
    <div style="margin-top: 10px; display: flex; align-items: center; gap: 12px">
      <el-button type="primary" :loading="submitting" @click="submit">提交建议</el-button>
      <span class="tip">提交时自动记录你的账号与时间，管理员会在后台查看</span>
    </div>

    <el-divider />
    <h4 style="margin: 0 0 8px">我的提交（{{ total }}）</h4>
    <el-table :data="items" size="small" stripe>
      <el-table-column prop="created_at" label="时间" width="190" />
      <el-table-column prop="content" label="内容" min-width="300" />
    </el-table>
    <el-empty v-if="!total" description="还没有提交过建议" :image-size="60" />
  </el-card>
</template>

<style scoped>
.tip { color: #909399; font-size: 13px; }
</style>
