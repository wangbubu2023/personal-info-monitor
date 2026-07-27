# 安全模型（SECURITY_MODEL）

> 目的：把「安全声明 = 实际保障」变成可审查的清单。每个防护机制一行：**防什么、不防什么、依据（代码位置）**。
> 新增/修改任何防护机制时必须同步更新本文件——写这一行的过程本身就是威胁模型审查（v1.4 审计的两个 P1：KDF 防了不存在的威胁、SSRF 漏了声称防住的 rebinding，都属于本可以在写这一行时暴露的偏差）。

## 部署假设（威胁模型边界）

单用户系统，后端与数据库运行在用户自己的机器或私有 VPS 上。信任本机操作系统与同机进程；不做多租户隔离。**明确不设防**：能读取部署机磁盘（含 `runtime-secrets.json`）的攻击者、本机恶意进程、物理访问。

## 防护机制清单

| 机制 | 防什么 | 不防什么 | 依据 |
|------|--------|----------|------|
| API Key 认证（`X-API-Key`，`secrets.compare_digest` 常量时间比较） | 未持 key 的网络客户端访问任何 API / `/metrics`；时序侧信道猜 key | key 泄露后的滥用（无轮换、无过期、无速率限制）；能读本机配置的进程 | `app/platform/auth/api_key.py` |
| CORS 精确白名单（`PIM_PUBLIC_URL` 自动加入；拒绝 `*` 与通配 origin，启动时校验报错） | 恶意网页借用户浏览器发起跨源调用（配合浏览器同源策略） | 非浏览器客户端——curl/脚本不受 CORS 约束，真正的门是 API key / Web session | `app/platform/config/settings.py::effective_cors_origins` |
| 凭据静态加密：写入用 `v4:`（HKDF-SHA256 + 每记录随机盐）；`v3/v2/legacy`（PBKDF2）仅保留解密兼容，更新时自动升级信封 | 数据库文件单独泄露时，cookie/会话/凭据的明文暴露 | 攻击者同时拿到 `ENCRYPTION_KEY`（`runtime-secrets.json`，与库同机）；运行时内存中的明文。注：不用高迭代 KDF 是**有意的**——主密钥为机器生成全熵，口令拉伸只对低熵人类口令有意义（v1.4 审计修正） | `app/platform/security/encryption.py`（模块 docstring 即设计依据） |
| SSRF 防护：`assert_public_http_target` 拒绝私有/回环/保留地址；解析后**按 IP 固定连接**（`_pin_request_to_ip`）；重定向手动逐跳复查（上限 5 跳） | 抓取用户可配 URL 时打到内网/云元数据地址；DNS rebinding（解析与请求之间换 IP）；重定向绕过 | 公网上的恶意内容本身；经允许协议的公网开放代理中转到目标 | `app/platform/security/ssrf.py`（rebinding 防护为 v1.4 审计修正） |
| Reader 结构化白名单渲染：正文只经受控 block 类型（paragraph/heading/image/quote/code/footnote/link）以 React 文本节点渲染；URL 经 `safeHttpUrl` 仅放行 http/https | 抓取内容中的 script 注入 / XSS；`javascript:` 伪协议链接与图片 | 钓鱼性质的文本内容；外链图片加载产生的第三方追踪 | `backend/app/domains/enrich/reader/shared.py` + `frontend/src/pages/ReaderPage.tsx::renderReaderBlock` |
| 秘密脱敏输出（启动日志只打印掩码 key） | 终端/日志文件泄露完整 API key | 其他代码路径把秘密写进日志（靠 review，无全局过滤器） | `app/platform/runtime/lifespan.py::_mask_secret` |
| 依赖安全扫描（CI：pip-audit + `npm audit --omit=dev`） | 已知 CVE 的依赖进入构建 | 0-day、未收录的供应链投毒 | `.github/workflows/ci.yml` security job |
| LLM 输出守门（翻译/简报拦截拒绝声明与幻觉输出） | 模型拒绝语/幻觉污染简报与译文（内容完整性，非机密性） | 提示注入操纵摘要立场——抓取的正文本身就是不可信输入 | `afd1335` 及后续 llm 守门实现 |

## 已知未覆盖项（诚实清单）

API key 无轮换机制；无请求速率限制；抓取内容对 LLM 的提示注入无系统性防护；`runtime-secrets.json` 依赖文件系统权限而非额外加密。接受这些风险的理由：单用户私网部署 + 攻击面主要来自抓取的公网内容，而非多用户边界。
