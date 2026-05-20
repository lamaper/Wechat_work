# 项目架构说明

## 1. 总体架构

项目是一个 Flask 单体应用，后端统一提供：

- API
- 登录鉴权
- 静态页面托管
- 微信回调入口

前端是原生 HTML/CSS/JS，不单独起前端服务。

## 2. 物理目录

```text
app/
├── backend/
│   ├── app.py
│   ├── modules/
│   │   ├── auth/
│   │   ├── ai/
│   │   ├── feature3/
│   │   ├── pages/
│   │   ├── diagnostics/
│   │   └── shared/
│   └── tests/
├── data/
└── web/
```

## 3. 启动装配

`app/backend/app.py` 启动顺序：

1. 加载 `.env`
2. 初始化 Flask
3. 初始化数据库
4. 同步 `auth_identities`
5. 启动 feature3 worker
6. 注册 auth/pages/ai/diagnostics/feature3 路由

这个顺序就是系统主装配顺序，不建议随意调整。

## 4. 模块职责

### 4.1 `modules/auth`

- BIT 登录
- Session 用户信息
- 权限位判断
- 登录拦截

### 4.2 `modules/ai`

- `/api/chat` 主链路
- FAQ 与知识库检索
- 公网搜索与网页抓取
- LLM 汇总输出

### 4.3 `modules/feature3`

- 工单生命周期（pending -> answered -> closed）
- 学长答复
- 微信回调与查询
- 异步任务 worker

### 4.4 `modules/pages`

- 页面路由与静态文件入口

### 4.5 `modules/shared`

- DB 访问
- 路径常量
- 文本工具函数

## 5. 三条主链路

### 5.1 登录链路

未登录访问受保护页面时重定向到 `/login`；访问受保护 API 时返回 401。

### 5.2 AI 链路

问题进入 `/api/chat` 后，先做规则判断，再走知识库与网页证据，最后调用 LLM 生成回答。

### 5.3 工单链路

新生提问入库，学长在答复台处理；微信端和网页端共享一套数据。

## 6. 运行时文件

后端目录会产生运行数据，例如：

- `feature3.db`
- `kb_meta.json`
- `kb_state.json`
- `kb_texts.json`
- `wechat_token_cache.json`

这些文件属于运行状态，不应提交到设计文档中当作代码结构。

## 7. 文档分层

- 当前有效文档：`README.md` 与 `docs/` 下非 history 文档
- 历史资料：`docs/history/`
