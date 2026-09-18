# OpsPilot Console · Liquid Glass

企业 IT 智能诊断工作台，与 FastAPI 同源部署。使用原生 JavaScript ES Modules、HTML 和 CSS，无需额外前端构建服务。

视觉风格为明亮液态玻璃：浅蓝白背景、悬浮透明导航、磨砂卡片、柔和蓝色主按钮。正文优先保证可读性，玻璃模糊仅用于导航、卡片和弹窗。支持减少动态效果及不支持 backdrop-filter 时的降级显示。

## 页面

- 工作台：真实服务状态、平台概况、诊断输入及常见故障入口。
- 智能诊断：多轮追问、诊断建议、意图置信度、主辅 Agent、路由依据、执行链路、结果导出。
- 诊断记录：浏览器内保存最近 30 次诊断，支持搜索和继续诊断。
- 知识库：查看知识片段、语义检索、知识来源筛选、添加 SOP / 历史案例。
- Agent & Skills：查看已加载 Agent、当前进程调用统计、Skills 内容及重新加载。
- 评测中心：读取已保存报告、查看失败用例、导出报告、主动运行快速或全量评测。

## 运行

在项目根目录执行 `docker compose up -d --build`，然后打开 http://localhost/ 。
更新后端容器后若 Nginx 尚未解析到新地址，可执行 `docker compose restart nginx`。

本地 Python 启动方式仍为 `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`，访问 http://localhost:8000/ 。需要先正确配置项目依赖与 `.env`。

## 文件职责

- `index.html`：页面入口。
- `styles.css`：样式入口。
- `styles/tokens.css`：颜色、字体、间距、圆角、玻璃模糊与阴影的统一变量。
- `styles/layout.css`：悬浮导航、侧栏和页面网格。
- `styles/components.css`：卡片、表单、诊断、知识、Skills、评测、弹窗组件。
- `styles/responsive.css`：桌面、平板、手机布局与可访问性降级。
- `app.js`：页面、交互、API 请求与浏览器记录。
- `ui.js`：图标、文本转义、受限 Markdown 渲染、消息提示、导出。

页面数据来自 `/health`、`/chat`、`/skills`、`/knowledge/documents`、`/search`、`/knowledge/add`、`/eval/latest` 和 `/eval/run`。打开页面只读取状态与已保存报告，不触发诊断或评测模型调用。

## 数据口径

- Agent 状态“已加载”表示服务已注册该 Agent，不代表对模型 API 进行了实时探测。
- 知识统计单位是存储片段，不是原始文件。
- 请求总耗时是浏览器实测的完整 `/chat` 往返时间；评测 P95 来自报告，当前包含 Judge 调用。
- 诊断记录保存在此浏览器的 localStorage；导出可留存，不提供跨用户同步。
- 评测界面原样展示现有合成离线评测结果，运行新评测会更新现有 baseline 报告，可先导出。
- 模型和用户文本在渲染前均转义，不执行 HTML 或嵌入脚本。

## 验证

`python -m unittest discover -s tests -v`

浏览器检查：诊断与追问、空输入、知识来源筛选、知识检索、Skills 详情、评测失败样本展开、历史搜索与移动端导航。

自动浏览器验证：`npm install --prefix tools/ui-qa` 后运行 `node tools/ui-qa/check.mjs`。使用系统安装的 Edge；加 `--live` 将实际执行知识检索、VPN 诊断及追问，产生少量模型 API 调用。截图和结果保存在 `tools/ui-qa/artifacts/`。
