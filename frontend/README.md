# 前端应用

Personal Information Monitor 前端应用，基于 React + TypeScript 构建。

## 技术栈

- **框架**: React 18
- **语言**: TypeScript
- **UI库**: Ant Design 5.x
- **状态管理**: Zustand
- **数据请求**: TanStack Query (React Query)
- **路由**: React Router v6
- **构建工具**: Vite

## 目录结构

```
src/
├── components/          # React组件
│   ├── Dashboard/       # 仪表板
│   ├── DigestView/      # 简报视图
│   ├── SourceList/      # 监控源列表
│   ├── Settings/        # 设置
│   └── common/          # 通用组件
├── pages/               # 页面
├── services/            # API服务
├── store/               # 状态管理
├── hooks/               # 自定义Hooks
├── types/               # TypeScript类型
└── utils/               # 工具函数
```

## 本地开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

## 页面说明

### 首页 (/)
- 显示今日统计数据
- 最新内容列表
- 快速操作入口

### 每日简报 (/digest)
- 按日期查看内容
- 按类型分组显示
- 支持标记已读、收藏

### 监控源管理 (/sources)
- 添加/编辑/删除监控源
- 手动触发抓取
- 查看抓取状态

### 设置 (/settings)
- 分类管理
- 关键词监控配置
