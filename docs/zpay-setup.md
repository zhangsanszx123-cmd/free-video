# ZPAY 支付宝支付：配置、测试与验收指南

> 协议依据：`docs/zpay.md` 与官网 https://z-pay.cn/doc.html（2026-11-13 实时核对一致；Context7 未收录 ZPAY）。
> 方案与规则见 [requirements.md](./requirements.md) 支付章节、架构见 [design.md](./design.md)。

## 1. 它是怎么工作的（一句话版）

用户在定价页点「开通」→ 本站后端生成**已签名**订单 → 浏览器跳到 ZPAY 支付宝收银台付款 → 付完跳回本站 `/pay/result` →
后端向 ZPAY **查单确认**已付款 → 开通/续费会员。ZPAY 还会向 `/api/pay/notify` 发“异步通知”，有公网地址时它最快；
没有公网地址时由「结果页查单 + 后台每 60 秒对账」兜底，所以本机开发也能完整走通。

## 2. 你需要做什么

### 2.1 注册 ZPAY 商户（只需一次）
1. 打开 https://z-pay.cn → 「注册/登录」，按提示完成实名认证（个人即可，无需营业执照）。
2. 在商户后台开通 **支付宝** 通道（本站只用 `alipay`）。
3. 在后台「API 信息」页复制 **商户ID（PID）** 和 **商户密钥（KEY）**。

> KEY 相当于密码：只写进 `backend/.env`（已在 .gitignore 中），不要提交 git、不要发给任何人、不要放进前端。
> 怀疑泄漏时立即在 ZPAY 后台重置密钥并更新 `.env`。

### 2.2 配置 `backend/.env`
```ini
ZPAY_PID=你的商户ID
ZPAY_KEY=你的商户密钥
ZPAY_GATEWAY=https://zpayz.cn
# 本站对外地址：用于拼 notify_url 和 return_url。必须是你在浏览器里打开本站用的地址。
PUBLIC_BASE_URL=http://127.0.0.1:8000
ZPAY_MOCK=false
PAYMENT_ORDER_TTL_MINUTES=30
PAYMENT_RECONCILE_SECONDS=60
```
修改后**必须重启后端**才生效。`PID/KEY` 都为空且 `ZPAY_MOCK=false` 时，定价页显示「在线支付暂未开放」，点击按钮弹出「会员在线支付功能即将上线」——这不是故障，说明支付未配置或未重启。
可用 `curl http://127.0.0.1:8000/api/plans` 确认：返回 `"payment_enabled":true` 才表示支付已开启。

启动命令（在 `backend` 目录）：`.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`。
若报 `[Errno 10048]`，说明 8000 端口已被另一个后端进程占用，先关闭它再启动（见 README「快速开始」）。

## 3. 第一步：零成本模拟演练（不需要 ZPAY 账号）

1. `.env` 中设 `ZPAY_MOCK=true`（PID/KEY 可留空），`PUBLIC_BASE_URL` 与浏览器地址一致：
   - 生产方式运行（`npm run build` 后 uvicorn :8000）→ `http://127.0.0.1:8000`
   - 开发方式运行（Vite `npm run dev`）→ 填 Vite 地址，如 `http://127.0.0.1:5173`
2. 启动后端，日志会提示 `ZPAY_MOCK=true: ... no real money`。
3. 登录 → 定价页 → 「开通月卡」→ 确认弹窗 → 「前往支付宝付款」→ 跳到**本机模拟收银台**（黄色“模拟支付 · 不会扣钱”标识）。
4. 可选按钮：
   - 「模拟支付成功」：发异步通知 + 跳回结果页（正常流程）。
   - 「支付成功但不发异步通知」：模拟你本机收不到通知的真实情况，验证结果页主动查单。
   - 「支付成功并重复发送 3 次通知」：验证幂等，会员只开通一次。
   - 「取消支付」：返回定价页，订单保持“待支付”。
5. 结果页显示「支付成功，会员已开通」；个人中心「会员与额度」可看到会员与「我的订单」。

`SESSION_SECURE=true`（生产配置）时模拟收银台会被拒绝启用，避免误上线。

## 4. 第二步：真实小额支付测试（本机无公网 IP）

1. `.env`：填好 `ZPAY_PID`/`ZPAY_KEY`，`ZPAY_MOCK=false`，`PUBLIC_BASE_URL=http://127.0.0.1:8000`。
2. 临时把月卡改成 1 分钱（在 `backend` 目录）：
   ```powershell
   .venv/Scripts/python -m app.membership configure monthly --price-cents 1 --monthly-seconds 36000
   ```
3. 重启后端，用一个测试账号在定价页开通月卡，用手机支付宝扫码/付款 0.01 元。
4. 付款后浏览器跳回 `http://127.0.0.1:8000/pay/result`，页面显示“正在确认” → 几秒内变为“支付成功”。
   这里 ZPAY 的异步通知**到不了你的电脑**（它访问不到 127.0.0.1），这是正常的；结果页和后台对账会调用
   ZPAY 查单接口确认付款。即使你直接关掉页面，后台每 60 秒也会核对 24 小时内的待支付订单。
5. 测完恢复价格：
   ```powershell
   .venv/Scripts/python -m app.membership configure monthly --price-cents 1990 --monthly-seconds 36000
   ```
6. 需要退回测试款：`.venv/Scripts/python -m app.payments refund 订单号 --allow-paid`（会员不会自动收回，测试账号可直接注销）。

（可选）想亲眼验证异步通知：用 cpolar / natapp 等内网穿透获得一个公网 https 地址，填入 `PUBLIC_BASE_URL` 并用该地址打开网站。

## 5. 业务规则（已确认）

| 当前身份 | 购买月卡 | 购买年卡 |
|---|---|---|
| 免费用户 / 会员已过期 | 立即开通 1 个月 | 立即开通 12 个月 |
| 月卡会员 | 续费：到期时间顺延 1 个月 | 升级：立即切换年卡，有效期 = 现在 + 12 个月 + 月卡剩余时长 |
| 年卡会员 | 不可购买（按钮禁用、后端 409） | 续费：到期时间顺延 12 个月 |

- 开通/升级用新套餐的月额度替换本月额度上限，**保留本月已用与预占**；续费沿用相同规则。
- 订单金额、套餐、额度在下单时从数据库快照，下单后改价不影响该订单。
- ZPAY 没有关闭订单接口，用户可能在旧收银台页面迟到付款：真实到账的钱一律记录；如因规则无法开通
  （年卡期间到账的月卡单、账号已注销），订单标记为「待退款」，管理员用退款命令处理。
- 同一用户同一套餐 30 分钟内的未支付订单会被复用，重复点击不会产生两笔可付款订单。

## 6. 安全措施清单

- 前端只提交套餐代码；价格、商品名、签名全部由后端生成，KEY 不出服务器、不写日志（查单 URL 也不记录）。
- 异步通知：MD5 验签（`hmac.compare_digest`）→ 商户号 → `TRADE_SUCCESS` → 订单存在 → 金额（按分精确比较）→ 支付方式，
  **然后再调用查单接口确认**（防 KEY 泄漏后的伪造通知）；查单失败返回 `fail` 让 ZPAY 稍后重试。
- 入账函数在一个 MySQL 事务内锁用户行和订单行，已处理订单直接返回 `success`；ZPAY 交易号唯一索引防一笔钱入两单。
  通知、结果页查单、后台对账同时到达也只开通一次（自动化测试 10 线程并发验证）。
- 下单接口需登录、校验来源、每用户 10 分钟 10 次限速；订单查询只能看自己的订单；接口均 `no-store`。
- 订单与流水（`payment_orders`、`payment_events`）在账号注销后保留（user_id 置空），用于财务核对。

## 7. 管理命令（在 backend 目录）

```powershell
.venv/Scripts/python -m app.payments orders                      # 最近 50 笔订单
.venv/Scripts/python -m app.payments orders --status refund_required
.venv/Scripts/python -m app.payments sync 订单号                 # 立即向 ZPAY 查单并入账
.venv/Scripts/python -m app.payments sync                        # 核对 24 小时内全部待支付订单
.venv/Scripts/python -m app.payments refund 订单号               # 全额退款「待退款」订单
.venv/Scripts/python -m app.payments refund 订单号 --allow-paid  # 退款已开通会员的订单（会员需人工处理）
```

## 8. 上线清单

- `PUBLIC_BASE_URL=https://你的域名`（notify_url 需公网可达、5 秒内应答）、`SESSION_SECURE=true`、`ZPAY_MOCK=false`。
- 商品名保持具体描述（如“FreeVideo Pro 月卡会员（视频转文字10小时/月）”），ZPAY 要求体现具体商品，否则易被封。
- 对账线程为单进程实现；多实例部署时只在一个实例开启（其余设 `PAYMENT_RECONCILE_SECONDS=0`）。

## 9. 自动化测试

- 后端：`cd backend && .venv/Scripts/python -m pytest tests/test_payments.py`（需 MySQL 测试库；ZPAY 全部为进程内模拟，不联网）。
- 浏览器：按 `frontend/tests/payment_ui.py` 文件头启动 :8011 测试后端（`ZPAY_MOCK=true` + 测试库）后运行 `python -P frontend/tests/payment_ui.py`。

## 10. 验收步骤（请你操作）

1. 模拟模式下：游客点「开通月卡」→ 弹登录 → 登录后自动出现支付确认弹窗，金额 ¥19.90。
2. 模拟收银台「模拟支付成功」→ 结果页成功，个人中心显示月卡会员、订单“已支付”、额度 10 小时。
3. 定价页按钮变为「续费月卡」「升级年卡」；升级后月卡按钮禁用并提示“年卡有效期内无需购买月卡”。
4. 「支付成功但不发异步通知」→ 结果页仍能在几秒内显示成功。
5. 「重复发送 3 次通知」→ 有效期只顺延一次。
6. 真实模式 0.01 元测试一次（见第 4 节），测完恢复价格。
