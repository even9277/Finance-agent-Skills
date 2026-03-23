# Finance 智投助手 — 前端 (Phase 1)

## 环境要求

- Node.js >= 18
- npm >= 9

## 安装依赖

```bash
cd frontend
npm install
```

## 启动开发服务器

```bash
npm run dev
# 访问 http://localhost:5173
```

> 需要后端运行在 http://localhost:8000，Vite 已配置代理 `/api` → 后端。

## 构建生产版本

```bash
npm run build
```

## 字体说明

使用 Google Fonts（`Noto Serif SC` + `Noto Sans SC`），需要网络访问。
离线环境可将字体文件下载至 `public/fonts/` 并修改 `index.html` 中的 `@import`。
