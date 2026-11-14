# N.E.K.O 桥接插件 v2.0.3

> 针对代码审查（7.4/10）的修复版本。
>
> - **下载校验加固**：不再用 GitHub API 取 "latest" 元数据；改为固定下载
>   3.1.6，URL 由常量拼接，下载后与**代码内写死的官方 SHA256** 比对。
>   哈希不符或版本未知一律拒绝（fail closed），缓存复用前也重新校验。
> - **危险接口二次确认**：`api_call` / `api_batch` 调用改密码、改账号、
>   改全局配置、改代理等写接口时，必须显式传 `confirm=true`。
> - **修正 `_spawn` 端口**：`WEB_PORT` 改用实际生效端口，避免与账户注册表错位。
> - **文档与代码对齐**：更新代理策略、下载策略的说明；`tools/` 下的接口目录
>   生成脚本已随仓库提供。
> - **测试补强**：38 项通过，新增哈希 fail-closed、固定版本 URL、危险接口
>   二次确认等用例（用轻量 SDK stub，无 SDK 环境也能跑）。

从「拉起 exe + 三个接口」升级为对 BiliLearn 3.1.6 的**全功能嫁接**。

## 新功能

- **开箱即用**：不再需要手动填 exe 路径。插件按
  「本地已装 → 自动下载固定版本 → 可选离线兜底」的顺序取得 BiliLearn，
  自动解包到插件数据目录后无头拉起。安装包不再放进仓库（不再有 100MB 的包袱），
  一律从 GitHub release 下载固定版本，**多镜像源自动切换**：
  gh-proxy.com → ghfast.top → 官方直连，单个源失败自动换下一个，
  全部失败才报错；下载后与代码内写死的官方 SHA256 比对。
- **自动登录面板**：BiliLearn 3.1.6 的面板对 `/api/*` 有「免责声明 → 登录」两道门槛，
  v1 的所有业务调用实际会被 401 挡下。v2 自动完成握手并保持会话 Cookie，
  会话失效时自动重登一次；凭据按 `配置 > 插件保存 > 预置默认` 顺序尝试，
  失败后进入冷却，避免触发面板的登录限流。
- **全量接口接入**：内嵌 BiliLearn 3.1.6 全部 **308 个 Web API** 的目录（含参数）。
  - 通用透传：`api_call`（任意接口）、`api_batch`（批量，最多 20 个）
  - 能力发现：`api_groups`（分组总览）、`api_search`（关键词搜索）、`api_describe`（某组详情）
- **41 个语义化入口**：机器人、实时监听、待机、B站扫码、视频总结/转网页/思维导图/弹幕、
  知识库、兴趣、搜索学习、学习目标、Agent、人格、心情、日记、日志、配置等。
- **端口自动对齐**：打包版 BiliLearn 会把端口写进账户注册表（`accounts.json`），
  v1 写死的端口会与真实端口错位。v2 启动后读取注册表，始终连到真实端口。
- **附接优先**：已在运行的实例直接附接；只有自己拉起的进程才负责停止。
- **exe 定位**：除上述自动安装链路外，仍支持配置路径、PATH、常见安装位置、
  自定义 `search_dirs` 及插件目录旁的浅层扫描。

## 入口数量

入口保持在 **43 个**（含 5 个通用透传），未列出的长尾功能全部通过 `bililearn_api_call` 触达。

## 兼容性

- 纯标准库实现（`subprocess` / `urllib` / `http.cookiejar` / `zipfile` / `asyncio`），
  零第三方依赖。
- 针对 BiliLearn **3.1.6** 生成接口目录；BiliLearn 升级后可用 `tools/` 下脚本重新生成。
- v1 的入口 id（`start` / `stop` / `restart` / `status` / `open_panel` / `bot_start` /
  `bot_stop` / `bot_status`）全部保留，原有调用方无需改动。

## 已验证

- 官方校验器 `neko-plugin check -r`：**通过**（包体约 51KB，不含安装包）。
- Ruff（市场门禁同款规则）：All checks passed。
- 插件测试套件：**38 项通过**（含镜像源顺序、镜像切换、全部源失败、
  写死哈希的 fail-closed、篡改拒绝、固定版本 URL、危险接口二次确认、
  分卷重组、解包幂等、zip-slip 防御、缓存清理）。
- 校验和来源交叉核对：GitHub Release 资产的 `digest` 与同 release 的
  `BiliLearn-3.1.6-SHA256SUMS.txt` 一致，均为
  `848a521aaa9420c4c85cbbeb749565b6f36163883cce587b68a3b814665fd9cf`
  （107,280,451 字节）。
- 镜像源可用性实测（2026-10-23）：官方 / gh-proxy.com / ghfast.top 均 HTTP 200
  且返回真实内容；ghproxy.net 超时、hub.gitmirror.com / github.moeyy.xyz 不可达。
- 真实下载实测（v2.0.2 阶段）：经 gh-proxy.com 下载 102.3MB，SHA256 与官方
  `SHA256SUMS.txt` 一致，解包出 exe，缓存复用生效。
- 真实 exe 端到端（v2.0.0 阶段）：解包 → `--serve` 拉起 → **3.3s 就绪** →
  自动登录 → `/api/info` 返回 version=3.1.6。
