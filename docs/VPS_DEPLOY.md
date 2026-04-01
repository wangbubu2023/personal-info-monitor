# VPS 部署说明（当前单进程架构）

本文档描述当前代码库在 Linux VPS 上的推荐部署方式。  
当前项目主运行模式为：

- 单个 FastAPI 进程
- SQLite 本地持久化
- FastAPI 同时托管 API 与前端静态资源

默认访问地址：

- `http://127.0.0.1:8000`

## 前置要求

- Python 3.11+
- Node.js 18+
- npm
- systemd（推荐，用于守护进程）

## 1. 拉取代码

```bash
git clone <你的仓库地址> personal-info-monitor
cd personal-info-monitor
```

## 2. 初始化

```bash
./pim setup
```

初始化会生成：

- `backend/.venv`
- `backend/.env`
- `frontend/dist`

## 3. 前台验证启动

```bash
./pim start --prod
```

浏览器访问：

- `http://127.0.0.1:8000`

确认正常后，再切换到守护方式。

## 4. 使用 systemd 守护（推荐）

创建服务文件：

```ini
[Unit]
Description=Personal Info Monitor
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/personal-info-monitor/backend
ExecStart=/path/to/personal-info-monitor/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

保存为：

```bash
/etc/systemd/system/personal-info-monitor.service
```

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable personal-info-monitor
sudo systemctl start personal-info-monitor
sudo systemctl status personal-info-monitor
```

## 5. 反向代理（可选）

若希望通过域名访问，可使用 Nginx 将请求反代到 `127.0.0.1:8000`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 6. 备份建议

重要数据位于 `DATA_DIR`，默认一般为：

```bash
~/.pim/data
```

建议定期备份：

- `pim.db`（SQLite 主库）
- `backend/.env`（或你实际使用的环境变量文件路径）
- **`runtime-secrets.json`**（位于 `DATA_DIR` 下，通常与 `pim.db` 同目录）

`runtime-secrets.json` 保存运行时密钥材料（用于加密与认证相关能力；若未在环境变量中显式提供对应密钥，应用会依赖该文件中的持久化值）。**若丢失该文件且没有其他可用的密钥备份，将无法解密库中已保存的历史凭据。** 仅备份 `pim.db` 与 `.env` 不足以保证可解密恢复，请务必将 `runtime-secrets.json` 一并纳入备份与异地保存策略。

推荐使用项目自带的备份命令（会执行 SQLite 热备份并归档 `backend/.env` 与 `runtime-secrets.json`，若存在）：

```bash
cd /path/to/personal-info-monitor
./pim backup
```

手动打包默认数据目录示例（包含 `pim.db` 与 `runtime-secrets.json`）：

```bash
tar -czvf ~/pim-data-$(date +%Y%m%d).tar.gz -C ~/.pim data
```

若 `.env` 不在上述目录内，请单独备份，例如：

```bash
cp /path/to/personal-info-monitor/backend/.env ~/pim-env-backup-$(date +%Y%m%d).txt
```

## 7. 更新流程

```bash
cd /path/to/personal-info-monitor
git pull
./pim setup
sudo systemctl restart personal-info-monitor
```

## 说明

- 当前代码库不再把 Docker、PostgreSQL、Redis、Celery 作为主部署方式。
- 如果后续重新引入多进程或外部数据库，请同步更新本文件与 README。
