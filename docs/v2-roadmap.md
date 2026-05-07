---
name: v2.0 规划 - GUI + 向量数据库
description: NoteMind v2.0 的规划方向：增加 GUI 界面和向量数据库支持，实现模糊语义检索
type: project
---

## v2.0 规划：GUI + 向量数据库检索

**状态：** 规划阶段，当前先完成 v1.x CLI 导入工具的打磨

### 需求
- **向量数据库**：实现语义搜索（模糊匹配），如搜索"芯片安全"能匹配相关内容即使原文没出现这个词
- **GUI 界面**：图形化界面方便检索和管理知识库

### 候选技术
- 向量库：ChromaDB、Faiss、Qdrant
- GUI：Gradio、Streamlit、Tauri + 前端

### 依赖
- v1.x CLI 导入工具需先完善（性能优化、拆分策略稳定）
- 导入阶段需同步生成向量索引（embedding）
