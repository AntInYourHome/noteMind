# NoteMind Release 自检清单

每次发布 release 前，逐项检查并通过。

## 1. 测试验证

- [x] 所有测试通过：`python -m pytest tests/ -v --ignore=tests/test_ocr_real_pdf.py --ignore=tests/test_ocr_spike.py`
- [x] 测试用例数 ≥ 60 个（当前 110 个）
- [x] v19 专项测试通过：`python tests/test_v19.py`（66 项）
- [x] parsers 测试通过：`python -m pytest tests/test_parsers.py -v`（38 项）

## 2. 功能验证

- [ ] **智能 OCR**：文字为主文档跳过 OCR，扫描版自动 OCR
- [ ] **AI 摘要**：300 字核心摘要，大文档按章节摘要
- [ ] **自动分类**：多级分类树（领域 → 平台/场景 → 具体系统）
- [ ] **自动打标**：每篇 3-8 个中文标签
- [ ] **文档双链**：基于标签/分类/内容相似度建立 `[[wikilink]]`
- [ ] **MD5 去重**：重复文件自动跳过
- [ ] **SQLite 状态**：`.notemind_status.db` 记录成功/失败/更新
- [ ] **文件更新检测**：MD5 + 大小 + mtime 变化检测，同路径更新正确识别
- [ ] **本地 VLM**：启动时测试 MiniMind-V 可用性
- [ ] **MOC 分割**：超过 500 条自动分割
- [ ] **不支持格式**：为未识别格式创建 MD 文档记录

## 3. 格式支持

- [ ] PDF（含智能 OCR）
- [ ] Word .docx / .doc（老版本通过 LibreOffice 转换）
- [ ] PPT .pptx / .ppt（老版本通过 LibreOffice 转换）
- [ ] Excel .xlsx / .xls（老版本通过 LibreOffice 转换）
- [ ] Markdown .md
- [ ] 图片 .jpg/.png/.gif/.bmp/.webp/.tiff/.svg
- [ ] SVG（XML 文本提取）
- [ ] 纯文本 .txt/.csv/.log

## 4. 代码质量

- [x] 无 console.log / print 调试残留（除正常日志外）
- [x] 无硬编码凭据（API key 等）
- [x] 错误处理完善（try/except）
- [x] SQLite UNIQUE 约束正确（`source_path` UNIQUE）
- [x] 模块导入错误处理完善（VLM 模块不存在时不崩溃）

## 5. 文档更新

- [x] README.md 版本号更新
- [x] README.md 版本历史章节更新
- [ ] config.json.example 同步更新（如有配置变更）

## 6. Release 打包

- [x] `release/` 目录包含完整文件
- [x] 不包含敏感文件（config.json, .env, logs/）
- [x] 包含 install.sh / requirements.txt
- [x] 包含 config.json.example

## 7. 已知 Bug 修复

- [ ] 同路径文件更新检测：`source_path` 加 UNIQUE 约束，`INSERT OR REPLACE` 正确生效
- [ ] VLM 模块导入错误：try/except 保护，is_available() 检查文件存在
- [ ] SVG 格式支持：`parse_svg()` 实现，`get_parser` 特殊处理

## 8. 快速冒烟测试

```bash
python -m pytest tests/test_smoke.py tests/test_dedup.py tests/test_parsers.py -v
```

- [ ] 冒烟测试全部通过
