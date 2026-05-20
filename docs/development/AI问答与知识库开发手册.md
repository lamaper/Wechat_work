# AI问答与知识库开发手册

## 1. 核心文件

- `app/backend/modules/ai/service.py`
- `app/backend/modules/ai/kb.py`
- `app/backend/modules/ai/web_fetcher.py`
- `app/backend/modules/ai/routes.py`

## 2. 问答主流程

`/api/chat` 处理大致分为：

1. 问题预处理
2. 本地知识库检索
3. 需要时触发网页检索
4. 组合证据调用 LLM
5. 返回回答和步骤信息

## 3. 知识库来源

知识库原始数据在 `app/data/`，以 Markdown 为主。

常见维护动作：

- 补充文档
- 重建索引（`/api/rebuild_index`）
- 用 `/api/kb_query` 做定向检索验证

## 4. 开发建议

- 改检索逻辑时同时验证“命中场景”和“未命中场景”
- 保留步骤信息，便于定位证据来源
- 出现低置信度结果时宁可保守，不要硬答
