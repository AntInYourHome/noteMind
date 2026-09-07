// 前端工具页面注册表：每新增一个工具页面，在此加一行。
// key 必须与后端模块目录名一致（如 server/app/modules/notes）。
export const registry = {
  notes: () => import('./notes/NotesView.vue'),
  log_parser: () => import('./log_parser/LogParserView.vue'),
  arm_registers: () => import('./arm_registers/ArmRegistersView.vue'),
  suggestions: () => import('./suggestions/SuggestionsView.vue'),
  samba: () => import('./samba/SambaTasksView.vue'),
}
