# 资讯快看 · InfoGather

个人自托管的 AI 资讯聚合阅读器：多源采集 → 去重聚类 → LLM 摘要 → 瀑布流阅读 → 原文直达。后端 FastAPI + SQLite，前端 Vue3 + Vite，可 Capacitor 打包成 Android APK。

## 目录

- `backend/` 采集/摘要服务 + REST API
- `app/` 移动端 Web（可套壳成 APK）

## 快速开始

### 1. 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env    # 填入 LLM_API_KEY / 生成 APP_KEY / 设置 PROXY_URL
.\.venv\Scripts\python -m app.serve          # 启动 API + 30min 定时采集/摘要
# 或手动跑一轮：
.\.venv\Scripts\python -m app.run_collect    # 采集
.\.venv\Scripts\python -m app.run_pipeline   # 摘要+聚类
```

`.env` 关键项：

| 变量 | 说明 |
|---|---|
| `LLM_API_KEY` | OpenAI 兼容网关的 key |
| `LLM_BASE_URL` | 如 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` / `LLM_MODEL_CHAIN` | 主模型 / 降级链，逗号分隔，超时或 5xx 自动切换 |
| `EMBED_MODEL` | 向量聚类模型；**留空则自动降级为 SimHash 标题聚类**，日后开放 embedding 直接填上即可无缝升级 |
| `APP_KEY` | 客户端访问密钥（64 位随机串），放入请求头 `X-App-Key` |
| `PROXY_URL` | 采集国外源所用代理，如 `http://127.0.0.1:7890` |

### 2. 前端

```powershell
cd app
npm install
npm run dev          # http://localhost:5173 ，开发模式经 Vite 代理连后端
```

浏览器打开后点右上 ⚙️，填后端 API 地址与 `APP_KEY` 即可（同源部署可留空地址）。

### 3. 打包 APK

本机需 JDK 21 与 Android SDK（platform-tools / platforms;android-35 / build-tools;35.0.0），已装好则：

```powershell
cd app
npm run build
npx cap sync android
$env:JAVA_HOME="C:\Android\jdk21"; $env:ANDROID_HOME="C:\Android\Sdk"
android\gradlew.bat -p android assembleDebug
# 产物 app\android\app\build\outputs\apk\debug\app-debug.apk
```

注：项目路径含中文时 `android/gradle.properties` 需保留 `android.overridePathCheck=true`。

### 4. 公网访问（Cloudflare Tunnel）

后端已单端口同时托管 H5 与 API（生产构建的 `app/dist` 存在时自动挂载），所以只需暴露 8000：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
# 日志中输出一段 https://xxx.trycloudflare.com 随机域名，手机浏览器直接访问
# 首次进入 ⚙️ 填入后端 .env 的 APP_KEY 即可
```

双击项目根的 `start.bat` 可一键拉起"后端 + 隧道"并打印当前公网地址。
注意：quick tunnel 域名随重启变化；需固定域名请注册 Cloudflare 账号改命名隧道（`cloudflared tunnel login` + 自有域名）。

## 采集漏斗

```
RSS 多源 → ①硬过滤(URL归一/SimHash去重/短正文/广告)
        → ②规则粗筛 → ③语义聚类(embedding 或 SimHash 降级)
        → ④LLM 摘要+相关性终审+热度排序 → SQLite → API → 瀑布流
```

## 免责声明

仅用于个人学习，采集遵守各源 robots 与频控；请勿高频抓取或二次分发受版权保护内容。
