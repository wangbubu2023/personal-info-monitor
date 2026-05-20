# 模块二：认证与安全 审计报告

## 总评

PIM 的安全姿态总体偏严谨：
- API Key 比较使用恒时算法；
- `/local-token` 的四道纵深防御（loopback IP / Host 头 / Origin / bootstrap_token）质量很高，针对 DNS rebinding 的防护是教科书级别；
- SSRF 不仅检查字符串还会重新解析 DNS 后逐 IP 复核；
- 凭据加密已演进到 PBKDF2 600k iterations + Fernet（OWASP 2023 推荐），envelope 版本化。

主要问题集中在**软件配置失败模式**与**几条 silent except**：解密异常静默丢弃凭据、`/local-token` 不在速率限制内、bootstrap fallback 生成的随机密钥可能在异常路径下导致历史密文不可解。无明显高危漏洞。

## 严重问题（❌）

无严重漏洞。

## 轻微问题（⚠️）

- **L1** `_load_existing_credentials` 解密失败静默吞异常返回空 dict，可能导致更新时把旧 credential 全部丢失（`backend/app/api/configs_api_auth.py:48-49`）。
- **L2** `/local-token` 与 `/health`、`/metrics`、`/livez` 都不在 `/api` 速率限制范围内，缺少对 bootstrap_token 暴力破解的速率约束（`backend/app/middleware/api_rate_limit.py:61-63`）。
- **L3** Settings 在缺少环境变量时会调用 `secrets.token_hex(16)` 等生成随机后备值，若 `runtime-secrets.json` 因任何原因被绕过，每次重启都会换密钥，历史加密数据不可恢复（`backend/app/config.py:111-117`）。
- **L4** `parse_cors_origins` 已拒绝 `*`，但 default 中包含 `http://tauri.localhost` 与 `https://tauri.localhost` 两条；前端实际只用 `tauri://localhost`（CORS regex 已覆盖），两条 http(s)://tauri.localhost 是历史残留，应清理（`backend/app/config.py:22-26`、`backend/app/main.py:188`）。
- **L5** `_load_existing_credentials` 与 `/local-token` 多处 `except Exception` 都在仓库 ruff 规则中需要 `# noqa: BLE001`，但目前没有；可能违反 ARCHITECTURE.md §9 的不变量。
- **L6** SSRF 防护属于"DNS 解析后再次校验 IP"，仍存在 TOCTOU 风险（解析与实际连接之间 DNS 可能变化），上层 HTTP 客户端没有 socket-level pinning。

## 良好实践（✅）

- **G1** API Key 比较使用 `secrets.compare_digest`（`backend/app/auth.py:22`），等价于 `hmac.compare_digest`，符合恒时比较要求。
- **G2** `/local-token` 端点四层防御（loopback IP → Host hostname → Origin → bootstrap_token）共同防止 DNS rebinding（`backend/app/main.py:324-362`）。
- **G3** `assert_public_http_target` 使用 `ipaddress` 标准库覆盖 private/loopback/link_local/reserved/multicast/unspecified，并对 `getaddrinfo` 解析后的所有 IP 重新校验（`backend/app/utils/ssrf.py:13-71`）。
- **G4** 加密 envelope v3：PBKDF2-HMAC-SHA256 600k iterations（OWASP 2023 起步线），Fernet（含 128-bit IV、HMAC-SHA256），每条记录独立 16 byte 随机 salt（`backend/app/utils/encryption.py:33-61`）。
- **G5** Cookie 跨主机阻断：在 `check_before_fetch` 中显式校验 cookie 来自的 host 与请求 host 一致（`backend/app/utils/ssrf.py:81-96`）。
- **G6** 安全头齐备：CSP（含 `frame-ancestors 'none'` + `base-uri 'self'`）、X-Content-Type-Options nosniff、Referrer-Policy no-referrer、X-Frame-Options DENY（`backend/app/main.py:42-57`）。
- **G7** `parse_cors_origins` 显式拒绝 `*` 与 `*.example.com` 通配，并在配置错误时 fail-fast（`backend/app/config.py:193-229`）。
- **G8** runtime-secrets.json 使用 0o600 chmod（`backend/app/config.py:147-151`）。
- **G9** `bootstrap_token` 比较也用 `secrets.compare_digest`（`backend/app/main.py:319`）。
- **G10** SSRF check 显式拒绝 `localhost` 字符串（`ssrf.py:59-60`），不依赖纯 IP 解析。

## 详细审计清单

### 1. auth.py：恒时比较与依赖注入完整性

- **结论：** ✅
- **代码位置：** `backend/app/auth.py:13-24`、`backend/app/main.py:200`
- **分析：**
  - `secrets.compare_digest(api_key, expected)` 等价于 `hmac.compare_digest`，避免 timing attack。
  - `APIKeyHeader(name="X-API-Key", auto_error=False)` + 自定义 401 信息，避免 FastAPI 默认错误格式。
  - **依赖注入分布：** `app.include_router(api_router, prefix="/api")`（`main.py:200`）没有在路由器级别强制注入 `verify_api_key`；保护需要每个子路由器或路由自己声明 `Depends(verify_api_key)`。`/health`（`main.py:365`）、`/metrics`（`main.py:407`）显式注入。`/livez`、`/local-token` 故意不注入（设计如此，前者公共健康检查，后者用 bootstrap_token 鉴权）。
  - **未在本次审计验证的事项：** `api_router` 在 `backend/app/api/__init__.py` 是否给所有子路由器都加了 `dependencies=[Depends(verify_api_key)]`。从 `configs_api_auth.py` 的 router 定义（L34）和路由声明（L102, L110, …）看不出依赖；这意味着保护应该是在 router 聚合层注入。
- **建议：**
  - 在 `audit/05-api-design.md` 模块对 `app/api/__init__.py` 做最终核验：是否在 `api_router` 层级注入 `Depends(verify_api_key)`，否则现有子路由器可能完全没有鉴权。

### 2. /local-token：Host 头与 X-Forwarded-Host 绕过

- **结论：** ✅
- **代码位置：** `backend/app/main.py:309-362`
- **分析：**
  - 4 层防御：(a) `real_ip` 必须是 `127.0.0.1` 或 `::1`；(b) Host 头去除端口后必须在 `{127.0.0.1, localhost, ::1, [::1]}`；(c) Origin 必须为空或在白名单；(d) `bootstrap_token` 时间安全比较。
  - `_hostname_of`（L279-293）正确处理 IPv6 字面量与 host:port 拆分。
  - **X-Forwarded-Host 是否能绕过？** Host 头校验直接读 `request.headers.get("host")`（L267, L349），而非 `X-Forwarded-Host`；攻击者无法通过该 header 影响判断。✅
  - **X-Real-IP 是否能绕过 loopback 检查？** `get_real_client_ip` 仅在 `TRUSTED_PROXY_IPS` 已配置且当前连接来自该 IP 时才信任 X-Real-IP（`api_rate_limit.py:36-42`）。默认 TRUSTED_PROXY_IPS 为空，本机部署不会读 X-Real-IP。✅
  - **DNS rebinding 防御**：核心在 (b) Host 头校验——攻击者控制的恶意域名解析到 127.0.0.1 后，浏览器仍会以恶意域名作为 Host，被 (b) 拒绝。
- **建议：** 无须改动，但建议把 `/local-token` 也纳入限速白名单（见 L2）以增加纵深防御。

### 3. ssrf.py：私网黑名单与 DNS 解析复检

- **结论：** ✅（基础设施完整）+ ⚠️（TOCTOU）
- **代码位置：** `backend/app/utils/ssrf.py:13-71`
- **分析：**
  - 黑名单使用 `ipaddress.ip_address(...)` 的标准属性 `is_private`（覆盖 RFC1918 全部）/`is_loopback`（127/8、::1）/`is_link_local`（169.254/16、fe80::/10）/`is_reserved`/`is_multicast`/`is_unspecified`（0.0.0.0、::）。这比手写 CIDR 更稳健。
  - DNS 解析使用 `loop.getaddrinfo`，把所有 family/proto 的解析结果合到 set，再逐一 `_is_private_address` 校验（L41-71）——典型的 SSRF 防护模式。
  - 拒绝 IPv6 unspecified `::`、unicast site-local（fec0::/10 在新版本 ipaddress 中已废弃；is_reserved 仍覆盖）。
  - **TOCTOU**：在 `assert_public_http_target` 与底层 HTTP client 实际打开 socket 之间，DNS 可被攻击者重新指向 127.0.0.1。这是这个模式的**已知边界**；要根治需要 socket-level pin（用解析后的 IP 直接 connect，并在 SNI/Host 中保留 hostname）。aiohttp/httpx 都不直接提供这类钩子。
  - 没有 IDN/punycode 显式归一化；但 `getaddrinfo` 会处理 IDNA encode，最终落到 IP 层校验，所以同样的 IP 黑名单仍然生效。
- **建议：**
  - 在文档（如 `docs/ARCHITECTURE.md` 或新增 ADR）声明"SSRF 防护到 DNS 复检为止，TOCTOU 是已接受的剩余风险"。
  - 长期：考虑把 outbound HTTP 客户端封装成 "解析一次→使用 resolved IP 直连 + Host header 改写" 的模式（仅对高敏感请求，如 `/api/sources/probe`）。

### 4. encryption.py：密钥来源 / 弱密钥 / IV 重用

- **结论：** ✅
- **代码位置：** `backend/app/utils/encryption.py:1-123`
- **分析：**
  - **算法**：Fernet = AES-128-CBC + HMAC-SHA256，每次 `encrypt()` 生成新 IV，绝对避免 IV 重用。
  - **密钥派生**：v3 使用 PBKDF2-HMAC-SHA256 600,000 iterations（OWASP 2023 推荐）+ 16-byte 随机 salt。salt 与 token 拼接 base64 存储。✅
  - **向后兼容**：v2（100k iterations）与 legacy（固定盐 + 100k）仍然可解密，但写入永远使用 v3。文档说"调用方 update credential 时触发自然 re-encrypt"——这是 lazy migration，正确但**不强制**——历史数据如果从未更新会一直停留在弱版本。
  - **密钥来源**：从 `settings.encryption_key`，即 `runtime-secrets.json` 的 ENCRYPTION_KEY 字段（`config.py:138-141`），文件 0600。
  - **弱密钥/硬编码**：`_LEGACY_STATIC_SALT = b"personal-info-monitor-salt"` 是一个公开常量，但仅作为 legacy 解密路径使用，不是加密密钥本身——加密密钥仍来自 runtime-secrets.json。✅
- **建议：**
  - 给 legacy / v2 envelope 提供一次性迁移命令（`pim secrets reencrypt-all` 或类似），主动把历史密文升级到 v3。
  - 在 `_decrypt_bytes` 加 `WARNING` 级别日志，标记 legacy/v2 envelope 命中，便于运维观察迁移进度。

### 5. configs_api_auth.py：解密异常处理 / 错误响应

- **结论：** ⚠️
- **代码位置：** `backend/app/api/configs_api_auth.py:37-50, 77-99, 309-349`
- **分析：**
  - `_load_existing_credentials`（L37-50）catch-all `except Exception: return {}`：若解密失败（密钥变化、payload corruption），函数返回空 dict 而不抛错。下游 `_merge_api_credentials` 会把当前 update 的字段塞进空 dict，`encrypt_data(existing_creds)` 把结果写回——结果是**所有未在本次 update 中显式提供的字段被默默丢失**（包括 api_secret、cookies、additional_config）。
  - 错误响应：`HTTPException(status_code=404, ...)` 等使用纯文本 detail，不泄露内部信息。✅
  - DELETE 端点（L309-349）做了"软清理"：把 Source.auth_config_id 和 BrowserSession.auth_config_id 置 NULL，再删除 AuthConfig，最后返回各被解链的行数。逻辑合理，FK 不会爆炸。⚠️ 但**审计角度**：这种"自动清理 FK"跨边界，应在 API 文档明确，否则用户可能以为 DELETE 无副作用。
  - 整个文件没有看到 `Depends(verify_api_key)`——依赖 `api_router` 层级注入。需要核对 `app/api/__init__.py` 的注入是否覆盖。
- **建议：**
  - `_load_existing_credentials` 应区分"empty payload"（合法）与"decryption failed"（异常），后者应记 ERROR 日志并向上抛 500，让操作员知道密钥/数据已损坏，不要悄悄覆盖。
  - DELETE 在响应里已显式返回 `sources_unlinked`/`browser_sessions_unlinked`，✅，建议在 API 文档（如 OpenAPI description）补一句"会自动解链关联资源"。

### 6. CORS 配置

- **结论：** ✅（实现）+ ⚠️（默认列表清理）
- **代码位置：** `backend/app/main.py:185-192`、`backend/app/config.py:17-27, 193-229`
- **分析：**
  - `parse_cors_origins` 显式拒绝 `*`、含通配符的 origin，以及非 http/https/tauri scheme（`config.py:214-225`）。
  - `allow_credentials=True` 与具体白名单组合是合规的（CORS 标准要求 credentials 不能配 `*`）。
  - `allow_origin_regex=r"^tauri://localhost$"` 锚定的精确正则，安全。
  - **默认 origin 列表里包含 `http://tauri.localhost` 与 `https://tauri.localhost`**（`config.py:24-25`）。"tauri.localhost"（带点的域名）与 "tauri://localhost"（自定义 scheme）不是同一个 origin。Tauri WebView 在不同平台上的 origin 表现不同：macOS 用 `tauri://localhost`，Windows 在某些 WebView2 版本上会变成 `http://tauri.localhost`。所以这不是漏洞、只是**依赖于平台行为的兼容字段**。但缺少注释说明。
  - `allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]` 不包含 HEAD/TRACE，合理。
  - `allow_headers=["Content-Type", "Authorization", "X-API-Key"]` 不放开任意头，最小化。
- **建议：** 在 `config.py:18-26` 加注释说明 `tauri.localhost` 的两种 origin 形态对应不同 Tauri/WebView 平台。

### 7. 速率限制：双维度与白名单覆盖

- **结论：** ⚠️
- **代码位置：** `backend/app/middleware/api_rate_limit.py:1-99`
- **分析：**
  - 限速 key = `IP:api_key前12字节`（L93-98），双维度均覆盖。✅
  - 仅对 `/api` 前缀生效（L62-63）。/livez、/health、/metrics、/local-token 都不在限速范围内。
    - /livez 公开探活，不限速合理；
    - /health 与 /metrics 已 `Depends(verify_api_key)`，被拒后 401 不会触发更深处的逻辑；攻击者用错误 API Key 重试也只是消耗 401 处理路径，影响有限；
    - **/local-token 是关键点**：仅靠 bootstrap_token（256-bit）+ loopback 限制，没有限速 → 在 loopback 上的恶意进程理论上可以无速率上限地试 token。token 强度足够使暴力破解不可行，但纵深防御应该有限速。
  - 内存安全：`_MAX_TRACKED_KEYS = 10_000` + 过期 key 主动清理（L70-71、L86-91）。✅
  - 只用 `time.monotonic()`，与系统时钟无关，正确。
- **建议：**
  - 将 `/local-token` 与 `/health` 也纳入限速。最小改动是在 dispatch 中把 path 判断从 `path.startswith("/api")` 扩展为 `path.startswith(("/api", "/health", "/local-token"))`。

### 8. 安全头（CSP、X-Frame-Options 等）

- **结论：** ✅
- **代码位置：** `backend/app/main.py:42-57, 444-475`
- **分析：**
  - CSP 主要 directive 都设置：default-src 'self'；script-src 'self'；style-src 'self' 'unsafe-inline' + Google Fonts；font-src 'self' + fonts.gstatic.com；img-src 'self' data: blob: https:；connect-src 'self' http://127.0.0.1:8000 http://localhost:8000；frame-ancestors 'none'；base-uri 'self'；form-action 'self'。
  - `'unsafe-inline'` 仅作用于 style-src（Ant Design 运行时注入需要），script-src 仍为 'self'，XSS 难以执行内联脚本。
  - X-Frame-Options DENY + frame-ancestors 'none' 双重保险。
  - 仅在 SPA HTML 响应头注入；JSON API 响应不需要这些 SPA-only 头部，省略合理。
  - SPA 路径内含目录穿越防护（L460-463 `os.path.realpath` + `startswith` 检查）。✅
- **建议：**
  - 考虑加 `Permissions-Policy`（前 Feature-Policy）禁用 camera/geolocation 等不需要的能力。

## 涉及文件

- `backend/app/auth.py`
- `backend/app/utils/ssrf.py`
- `backend/app/utils/encryption.py`
- `backend/app/api/configs_api_auth.py`
- `backend/app/main.py`（/local-token、CORS、安全头、SPA serving）
- `backend/app/middleware/api_rate_limit.py`
- `backend/app/config.py`（CORS、runtime-secrets）

## 威胁场景（高价值）

1. **DNS rebinding 窃取 API Key**：恶意网站把自己的域名解析到 127.0.0.1:8000，让用户浏览器请求 `/local-token`。Host 头校验（main.py:350）会让该请求带恶意域名的 Host → 被 403。✅ 防御有效。
2. **本地恶意进程读取 API Key**：另一个本地用户进程访问 `/local-token`。需要 (a) loopback ✅、(b) Host 正确 ✅、(c) Origin 正确 ✅、(d) bootstrap_token。bootstrap_token 在 `runtime-secrets.json` 0600 文件，跨用户不可读。✅ 防御有效。
3. **SSRF 通过用户提交 URL 探测内网**：probe / 采集器内部都调用 `assert_public_http_target` → DNS 解析后所有 IP 复检 private/loopback。✅ 主要风险在 TOCTOU。
4. **凭据数据库被读出**：encryption_key 在 0600 文件、不在 DB 内；即使 DB 被偷也无法解密。✅
5. **加密密钥变换后追加 update 导致历史凭据丢失**（L1）：`_load_existing_credentials` 静默吞解密异常 → 用户以为更新了 1 个字段，实际把 cookies/api_secret 全部丢失。虽不是攻击向量，但用户体验是悄无声息的数据丢失。
