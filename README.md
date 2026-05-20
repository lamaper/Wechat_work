# 北京理工大学新生助手

一个面向新生场景的 Web + 微信公众号项目，核心能力包含：

- AI 问答（知识库 + 公网检索）
- 地点查询（腾讯地图）
- 人工工单（新生提问、学长答复、微信回查）
- 统一登录与权限控制

## 1. 项目状态

当前代码已经进入稳定维护阶段，目录结构和主链路都已固定：

- 后端入口固定为 `app/backend/app.py`
- 核心业务固定在 `app/backend/modules/`
- 前端页面固定在 `app/web/`
- 知识库源文件固定在 `app/data/`
- 历史文档统一归档在 `docs/history/`

## 2. 快速启动（Windows）

### 2.1 进入后端目录

```powershell
Set-Location .\app\backend
```

### 2.2 启动 Python 环境

当前仓库实测可用环境：

```powershell
conda activate D:\envs\wechat_work
```

### 2.3 安装依赖

```powershell
pip install -r requirements.txt
```

如需向量检索能力，再安装：

```powershell
pip install -r requirements-rag.txt
```

### 2.4 准备配置

```powershell
Copy-Item .\.env.example .\.env
```

至少配置这些字段：

- `SECRET_KEY`
- `WECHAT_TOKEN`
- `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`

地图功能还需要在 `app/web/place.html` 中填写腾讯地图 Key。

### 2.5 启动服务

```powershell
D:\envs\wechat_work\python.exe .\app.py
```

默认地址：`http://127.0.0.1:5000`

## 3. 目录说明

```text
Wechat_work/
├── app/
│   ├── backend/        # Flask 后端
│   ├── data/           # 知识库 Markdown
│   └── web/            # 前端页面
├── deploy/             # Nginx / systemd / nssm 配置示例
├── docs/               # 当前文档 + 历史归档
└── screenshots/        # 截图
```

## 4. 常用验证

在 `app/backend` 目录执行：

```powershell
D:\envs\wechat_work\python.exe .\tests\feature3_smoke_test.py
D:\envs\wechat_work\python.exe .\tests\url_fetch_smoke_test.py https://www.bit.edu.cn --search-query "北京理工大学 选课"
```

## 5. 文档入口

- 架构说明：`ARCHITECTURE.md`
- 开发文档：`docs/development/`
- 部署文档：`docs/deployment/`
- 测试文档：`docs/testing/测试与验收手册.md`
- 历史文档：`docs/history/`

## 6. 说明

`docs/history/05-现行说明文档归档/` 保存了本轮迁移前的全部说明文档原件，便于追溯。
