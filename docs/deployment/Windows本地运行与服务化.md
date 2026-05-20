# Windows 本地运行与服务化

## 1. 本地运行

```powershell
Set-Location .\app\backend
conda activate D:\envs\wechat_work
D:\envs\wechat_work\python.exe .\app.py
```

默认访问：`http://127.0.0.1:5000`

## 2. 本地常见问题

- 端口冲突：5000 被占用
- 环境错误：没用到项目 Python 环境
- 配置缺失：`.env` 或地图 Key 未配置

## 3. Windows 服务化

可使用 NSSM 托管 Python 进程，参考：`deploy/windows/nssm-service.md`。

建议服务化前先在命令行连续运行一天，确认日志和稳定性。
