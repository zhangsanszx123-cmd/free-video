# 后台界面美化验证

日期：2026-11-17。范围：仅 `/admin/*` 前端视觉，不改后端、接口、路由与业务逻辑。

## 改动

- `frontend/src/style.css`：新增 `admin-*` 样式类（侧栏、卡片、表格、徽章、骨架屏、登录分栏、隐藏滚动条的内容区），未改动前台已有 token。
- `AdminLayout.vue`：深色侧栏、52px 顶栏与面包屑、固定屏高外壳，手机抽屉导航。
- `AdminStatus/AdminPagination/AdminDialog.vue`：徽章、适中分页、对话框动效。
- 六个页面（登录、注册用户、后台账号、会员价格、套餐额度、提取记录）统一页头、工具栏、表格行与提示条，兼顾呼吸感与一屏无滚动条。

## 测试适配

抽屉导航使 390px 下侧栏链接默认不可见，`admin_pricing_ui.py`、`admin_limits_ui.py`、`admin_history_ui.py`、`admin_real_ui.py` 在窄屏先点「打开导航菜单」，断言后再点「关闭导航菜单」。新增 `frontend/tests/admin_fit_ui.py` 断言 10 条数据时页面与内容区无滚动。

## 自动化结果

| 检查 | 结果 |
|---|---|
| `npm run build` | 通过 |
| `admin_ui.py` | 7 项通过 |
| `admin_pricing_ui.py` / `admin_limits_ui.py` / `admin_history_ui.py` | 1440、1024、390 宽度通过 |
| `admin_fit_ui.py` | 1440×860、1920×900 五个页面均无页面或内容区滚动 |
| `ui_regression.py`、`admin_races.mjs` | 22 项通过、9 项通过 |

## 人工验收

重新构建后刷新 `http://localhost:8000/admin/users`，依次查看六个页面和三类对话框；缩小窗口到手机宽度检查抽屉开合。

未运行：真实后端的 `admin_real_ui.py`（需隔离测试库服务 :8015），只改了窄屏打开抽屉的步骤，待你需要时再跑。
