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
git clone --depth 1 https://github.com/wangbubu2023/personal-info-monitor.git
cd personal-info-monitor
```

如需固定在 1.4.0 稳定版：

```bash
git clone --depth 1 --branch v1.4.0 https://github.com/wangbubu2023/personal-info-monitor.git
cd personal-info-monitor
```

## 2. 初始化

```bash
./pim setup
```

`setup` 默认会安装 browser-backed collector 所需的 bundled Chromium，尝试安装 Linux
系统运行库，并运行一次 `about:blank` smoke test。smoke test 不通过时，安装会直接失败并给出
可操作提示，避免第一次动态网页抓取才暴露浏览器不可启动。

如果 VPS 只使用 RSS / 普通网页抓取，暂时不需要浏览器登录、X、复杂动态网页抓取，可以先跳过
浏览器 bootstrap，减少首次安装体积：

```bash
./pim setup --skip-playwright
```

后续需要时再安装：

```bash
./pim setup
```

如果系统包由镜像预装或由运维平台统一管理，可只跳过 Linux 系统包安装：

```bash
./pim setup --skip-playwright-deps
```

RHEL / TencentOS / CentOS / Fedora 系发行版可手动安装以下 Chromium 运行库：

```bash
sudo dnf install -y mesa-libgbm mesa-libEGL libdrm libX11 libXcomposite libXdamage \
  libXext libXfixes libXrandr libxcb libxkbcommon cairo pango glib2 gdk-pixbuf2 \
  atk at-spi2-atk at-spi2-core nss nspr alsa-lib cups-libs dbus-libs fontconfig \
  freetype libxshmfence expat
```

默认浏览器 channel 是 bundled Chromium。只有在服务器已安装 Google Chrome 且明确需要时，才设置：

```bash
PIM_PLAYWRIGHT_CHANNEL=chrome
```

Linux 容器或 root-run 服务默认使用 `PIM_PLAYWRIGHT_NO_SANDBOX=auto`，会自动注入
`--no-sandbox --disable-setuid-sandbox`。如平台探测不准，可显式设为 `always` 或 `never`。

注意：X 登录态捕获必须使用可视化浏览器，让用户手动完成 CAPTCHA/2FA。纯 headless 模式无法可靠拿到
`auth_token` / `ct0`。VPS 容器如果没有 `DISPLAY` / `WAYLAND_DISPLAY`，请在桌面环境操作，或用
`xvfb-run` / 系统级 Xvfb 启动 PIM 服务后再打开浏览器会话登录。

如果目标站点在 VPS 上无法稳定登录，优先使用本地 Auth Bundle 流程：在本地可信电脑上打开可视化浏览器登录，
生成一个登录态包，再导入 VPS。导入后 PIM 会写入现有 `AuthConfig`，并在包内含有 Playwright
`storage_state` 时保存到 VPS 的 browser-session 目录，后续抓取可直接复用。

推荐用一条命令完成本地采集、上传 VPS、远端导入。命令会把临时 bundle 上传到 VPS 的
`/tmp/pim-auth-bundles/`，导入结束后默认删除远端临时文件；远端 `pimctl` 会优先读取 VPS 自己的
`~/.pim/data/runtime-secrets.json` 或已登录 profile：

```bash
./pim login-sync https://example.com \
  --remote pim@your-vps \
  --remote-pim ~/personal-info-monitor
```

如果远端 PIM 不在本机 `http://127.0.0.1:8000`，可显式传远端服务地址或 profile：

```bash
./pim login-sync https://example.com \
  --remote pim@your-vps \
  --remote-pim ~/personal-info-monitor \
  --remote-server https://your-pim.example.com \
  --remote-profile production
```

排障时仍可拆成两步：

```bash
./pim capture-session https://example.com --out example.pim-auth-bundle.json
# 等价入口：./pim auth-bundle export https://example.com --out example.pim-auth-bundle.json

scp example.pim-auth-bundle.json pim@your-vps:/tmp/example.pim-auth-bundle.json
ssh pim@your-vps 'cd ~/personal-info-monitor && ./pimctl auth-bundle import /tmp/example.pim-auth-bundle.json && rm -f /tmp/example.pim-auth-bundle.json'
```

Auth Bundle 文件包含可复用登录 cookie，等同于账号登录权限。只在可信通道传输，导入完成后删除临时文件。

### 2.1 X / RSSHub / 官方 API 策略

X 监测源默认按 `GraphQL/Cookie -> RSSHub -> Nitter` 顺序抓取。`X_BEARER_TOKEN`
对应官方 X API，属于付费/配额 fallback；即使在环境变量里配置了 Bearer Token，PIM 也不会自动调用。
只有给单个信源显式设置 `metadata.strategy=api` 或 `metadata.allow_x_api_fallback=true` 时才会走官方 API。

VPS 上建议使用自建 RSSHub，避免公共实例限流或不可用影响 X fallback：

```ini
Environment=RSSHUB_URL=https://rsshub.your-domain.com
```

仓库提供了一个 Redis 缓存 + browserless 的基线 Compose 文件，可直接放到 VPS 独立目录运行：

```bash
mkdir -p /opt/rsshub
cp docs/rsshub-docker-compose.yml /opt/rsshub/docker-compose.yml
cd /opt/rsshub
docker compose up -d
curl -f http://127.0.0.1:1200/healthz
```

建议只把 RSSHub 监听在本机端口，再通过 Nginx/Caddy 暴露 `https://rsshub.your-domain.com`，最后把
PIM 的 `RSSHUB_URL` 指到该 HTTPS 地址。

RSSHub 自建实例如果需要访问带登录态的路由，请按 RSSHub 官方方式配置对应 cookie。PIM 不会把本地
Auth Bundle 中的 cookie 自动转发给 RSSHub；两边登录态需要分别管理。

### 2.2 合规与账号风险边界

登录态、Auth Bundle、X Cookie 与站点会话只应使用你有权访问的账号和内容。不同站点对自动化访问、
Cookie 复用、异地 IP、付费内容抓取和第三方 API 使用有不同服务条款；启用前请自行确认。VPS/headless
环境更容易触发验证码、风控或账号锁定，因此默认推荐复用已导入的会话，避免服务器自动跑密码登录。
PIM 只做本地个人信息监控，不提供绕过访问控制、共享付费内容或规避平台限制的保证。

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
WorkingDirectory=/path/to/personal-info-monitor
ExecStart=/path/to/personal-info-monitor/pim up --foreground --server
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PIM_PUBLIC_URL=https://your-domain.com
Environment=PIM_DISABLE_PASSWORD_AUTO_LOGIN=true

[Install]
WantedBy=multi-user.target
```

VPS/headless 服务推荐保留 `PIM_DISABLE_PASSWORD_AUTO_LOGIN=true`：抓取时只复用已导入的
cookie / browser-session，不在服务器上自动驱动密码登录，避免在无显示环境或异地 IP 上触发验证码、风控或账号风险。
确实需要给某个信源回退密码登录时，先取消该全局开关，再为信源显式设置
`metadata.allow_password_login=true`。

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

`PIM_PUBLIC_URL` 用于生成公网引导链接。服务启动后可执行：

```bash
cd /path/to/personal-info-monitor
./pim bootstrap-url --origin https://your-domain.com
```

或使用环境变量：

```bash
PIM_PUBLIC_URL=https://your-domain.com ./pim bootstrap-url
```

## 4.1 无 systemd 容器守护

如果运行环境没有 systemd（例如 OpenClaw / 轻量容器），不要依赖 `./pim up`
的一次性后台进程长期存活。用外部 HEARTBEAT、cron 或平台心跳反复调用：

```bash
cd /path/to/personal-info-monitor
./pim ensure --server
```

`ensure` 会检查 PID 文件、进程表、8000 端口和 `GET /livez`。服务健康时直接退出；
PID 陈旧时会清理；PIM 进程存在但 `/livez` 不返回 HTTP 200 时会重启；如果 8000
端口被非 PIM 进程占用则失败退出，避免双启。

需要明确重启时可执行：

```bash
./pim restart --server
```

Linux 后台 PID 文件默认写入 `~/.pim/run/pim.pid`；可用 `PIM_PID_FILE=/path/to/pim.pid`
覆盖。旧版 `~/.pim/pim.pid` 会被自动识别并迁移。detached 模式下主日志
`~/.pim/data/pim.log` 默认超过 1MB 时轮转到 `pim.log.1`；可用
`PIM_LOG_ROTATE_BYTES=0` 关闭，或设置为其它字节数。

## 5. 反向代理与安全加固

### 5.1 HTTPS（必须）

通过域名公网访问时 **必须启用 HTTPS**，否则 API Key 会以明文传输。推荐使用 Caddy（自动证书）或 Certbot + Nginx。

**Caddy 示例**（最简方式，自动申请 Let's Encrypt 证书）：

```
your-domain.com {
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Real-IP {remote_host}
    }
}
```

**Nginx + Certbot 示例**：

```nginx
# 先用 certbot 申请证书：
# sudo certbot --nginx -d your-domain.com

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        # 必须传递真实客户端 IP，否则限速和本地令牌检查将失效
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}
```

### 5.2 配置 TRUSTED_PROXY_IPS

使用反向代理时，**必须**将代理的 IP 加入 `TRUSTED_PROXY_IPS`，否则：

- `/local-token` 端点的 loopback 检查将以代理 IP 为准，导致所有请求被拒绝（403）
- 速率限制将把所有流量视为同一 IP，失去精确的 per-client 效果

在 systemd 服务文件中添加：

```ini
[Service]
...
# 代理在本机时填 127.0.0.1，外部代理填其实际 IP
Environment=TRUSTED_PROXY_IPS=127.0.0.1
```

或在 `.env` 中：

```
TRUSTED_PROXY_IPS=127.0.0.1
```

### 5.3 防火墙（推荐）

仅暴露必要端口，阻止直接访问 8000：

```bash
# UFW 示例
sudo ufw default deny incoming
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# 不要开放 8000！FastAPI 通过 127.0.0.1:8000 仅本地监听
sudo ufw enable
```

### 5.4 加密主密钥保护

`runtime-secrets.json` 中的 `ENCRYPTION_KEY` 用于解密所有已保存凭据。  
在 VPS 上建议通过环境变量注入而不依赖文件（避免文件被读取后密钥泄露）：

```ini
[Service]
...
# 从安全来源（如 Vault、systemd Credentials）注入，不写入文件
Environment=ENCRYPTION_KEY=<your-key>
Environment=PIM_API_KEY=<your-api-key>
```

使用 **systemd Credentials**（systemd ≥ 250）：

```bash
sudo systemd-creds encrypt --name=ENCRYPTION_KEY -
# 粘贴密钥后 Ctrl+D，将输出添加到 [Service] 的 LoadCredentialEncrypted= 中
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

### 6.1 使用 systemd timer 自动备份

创建备份 service：

```ini
# /etc/systemd/system/pim-backup.service
[Unit]
Description=Backup Personal Info Monitor data

[Service]
Type=oneshot
WorkingDirectory=/path/to/personal-info-monitor
ExecStart=/path/to/personal-info-monitor/pim backup
```

创建每日 timer：

```ini
# /etc/systemd/system/pim-backup.timer
[Unit]
Description=Run PIM backup daily

[Timer]
OnCalendar=*-*-* 03:20:00
Persistent=true

[Install]
WantedBy=timers.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pim-backup.timer
systemctl list-timers pim-backup.timer
```

`./pim backup` 默认写入 `~/.pim/backups/`。生产环境还应把该目录同步到另一台机器或对象存储。

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
./pim upgrade --server --skip-playwright --systemd personal-info-monitor
```

`./pim upgrade` 会先备份 SQLite 与运行时密钥，再执行 `git pull --ff-only`，然后刷新 Python
依赖和前端静态资源。带 `--systemd personal-info-monitor` 时，最后会执行
`systemctl restart personal-info-monitor`（非 root 时才尝试 `sudo`）。如果当前容器没有 systemd，
升级会跳过 systemd 重启并给出提示，不会因为 `systemctl` 不可用而中断。

如果你没有使用 systemd，而是用 `./pim up` / `./pim start --prod` 启动，直接执行：

```bash
./pim upgrade --server --skip-playwright
```

无 systemd 容器建议让升级末尾走同一套健康检查和自愈入口：

```bash
./pim upgrade --server --skip-playwright --restart-mode ensure
```

如果 VPS 部署固定在 tag / detached HEAD，先用外部发布流程切到目标版本，然后执行：

```bash
./pim upgrade --server --skip-playwright --no-pull --no-restart
```

随后由 HEARTBEAT、cron 或平台心跳继续调用：

```bash
./pim ensure --server
```

## 8. 中文金融 / 科技舆情源

项目不内置一套“默认中文金融源”。VPS 首次部署建议先从稳定的 RSS / website 类型开始，
再按需要增加 X、YouTube、Podcast。这样可以降低登录态、Chromium、上游反爬变化带来的维护成本。

推荐顺序：

1. 优先添加官方 RSS、交易所/公司公告、媒体栏目页等稳定 URL。
2. 对没有 RSS 的网站使用 `website` 类型，让系统做网页探测。
3. X、YouTube、Podcast 只在确实需要时启用，并单独配置对应凭据或浏览器会话。

## 说明

- 当前代码库不再把 Docker、PostgreSQL、Redis、Celery 作为主部署方式。
- 当前依赖包覆盖 RSS、网页正文抽取、浏览器抓取、X、YouTube、Podcast 等能力，首次安装较重；
  轻量 VPS 可用 `./pim setup --skip-playwright` 先跳过 Chromium，后续再按需补装。
- 如果后续重新引入多进程或外部数据库，请同步更新本文件与 README。
