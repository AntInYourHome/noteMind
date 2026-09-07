<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const items = ref([])
const total = ref(0)
const classes = ref(['通用寄存器', 'PSTATE', '系统寄存器', '浮点/NEON'])
const query = reactive({ skip: 0, limit: 50, keyword: '', klass: '' })

async function load() {
  const { data } = await api.get('/tools/arm_registers', { params: query })
  items.value = data.items
  total.value = data.total
}

function search() {
  query.skip = 0
  load()
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制：${text}`)
  } catch {
    /* 浏览器不支持时忽略 */
  }
}

function pageChange(page) {
  query.skip = (page - 1) * query.limit
  load()
}

onMounted(async () => {
  try {
    const { data } = await api.get('/tools/arm_registers/classes')
    classes.value = data
  } catch {
    /* 用默认分类 */
  }
  load()
})
</script>

<template>
  <el-card>
    <template #header>🔧 ARM(AArch64) 寄存器查询（{{ total }} 条）</template>

    <div style="display: flex; gap: 12px; margin-bottom: 12px">
      <el-input
        v-model="query.keyword"
        placeholder="按名称 / 编码 / 描述搜索，如 SCTLR、ESR、页表"
        clearable
        style="width: 340px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-radio-group v-model="query.klass" @change="search">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button v-for="c in classes" :key="c" :value="c">{{ c }}</el-radio-button>
      </el-radio-group>
    </div>

    <el-table :data="items" stripe>
      <el-table-column prop="name" label="名称" width="150">
        <template #default="{ row }">
          <el-link type="primary" @click="copy(row.name)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="klass" label="类别" width="100" />
      <el-table-column prop="el" label="EL" width="60" />
      <el-table-column label="编码" width="130">
        <template #default="{ row }">
          <span v-if="row.encoding">{{ row.encoding }}</span>
          <span v-else style="color: #c0c4cc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="访问示例" width="210">
        <template #default="{ row }">
          <template v-if="row.klass === '系统寄存器' || (row.klass === 'PSTATE' && row.encoding)">
            <el-link @click="copy(`MRS X0, ${row.name}`)">MRS X0, {{ row.name }}</el-link>
            <el-link style="margin-left: 10px" @click="copy(`MSR ${row.name}, X0`)">MSR {{ row.name }}, X0</el-link>
          </template>
          <span v-else style="color: #c0c4cc">指令操作数</span>
        </template>
      </el-table-column>
      <el-table-column prop="desc" label="说明" min-width="300" show-overflow-tooltip />
    </el-table>

    <el-pagination
      style="margin-top: 16px; justify-content: flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="query.limit"
      :current-page="query.skip / query.limit + 1"
      @current-change="pageChange"
    />
  </el-card>
</template>
