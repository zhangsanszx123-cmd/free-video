# 邮箱账号：当前方案与接口

日期：2026-11-15。本文只描述最终实现；需求与架构文档中的早期条目属于历史决策。

## 当前行为

- 账号弹窗按「登录 / 注册 / 找回密码」排列，切换时保留当前页面和登录后待继续的操作。
- 注册填写邮箱、一个密码和算术图形验证码，不填写昵称或确认密码。昵称默认邮箱前缀，可在个人中心修改。
- 验证码为个位数加减题，结果 0–18、减法无负数，输入框和图片同行；点击图片刷新，无「换一张」文字按钮。有效期 5 分钟、浏览器绑定、一次消费，答案只存服务端摘要。
- 登录仅需邮箱密码；未验证账号不能登录。重发验证邮件需原注册邮箱密码，不需图形验证码，间隔 60 秒。
- 本机启用邮件链接验证：注册先创建待验证账号，30 分钟内点击邮件链接并在网页确认，才激活并自动登录。验证前不发放额度或认领游客时长。
- 找回密码输入注册邮箱，邮件链接 30 分钟有效、一次消费；重置成功撤销全部设备会话，使用新密码重新登录。未知邮箱统一提示；待验证账号也可通过此流程完成邮箱验证。
- 已完成用户要求的旧业务账号、订单和流水清空；迁移与应用启动不执行清空操作。

## 接口

| 接口 | 请求 / 响应 |
|---|---|
| GET `/api/auth/captcha` | `{id,image,expires_in}`，PNG data URL，无答案 |
| POST `/api/auth/register` | `{email,password,captcha_id,captcha_answer}`；后端兼容可选 nickname，当前界面不提供 |
| POST `/api/auth/login` | `{email,password}` |
| POST `/api/auth/resend-verification` | `{email,password}` |
| POST `/api/auth/verify-email` | `{token}`，成功自动登录 |
| POST `/api/auth/forgot-password` | `{email}`，统一提示 |
| POST `/api/auth/reset-password` | `{token,password}`，成功不自动登录 |
| DELETE `/api/account` | `{password,confirm_email}` |

邮箱去首尾空格、按小写唯一处理，不合并加号别名；密码 8–128 字符，不可全空白或等同邮箱。个人中心、会员、额度、历史、订单仍关联同一用户 ID，保留内部随机用户名。

## 配置与验收

- [163 SMTP 配置与邮箱验证](./email-verification-setup.md)
- [找回密码与最终测试记录](./password-recovery-verification.md)
- [最初免验证阶段的历史记录](./email-auth-verification.md)

`AUTH_EMAIL_VERIFICATION_REQUIRED` 默认 false；本机 `.env` 已设为 true。SMTP 密钥只保存在被 Git 忽略的 `.env`，不提交。正式上线需将 PUBLIC_BASE_URL 改为可访问的 HTTPS 地址；当前 localhost 链接只能在运行网站的电脑使用。

验证码与大部分限速为单进程内存模型；邮件 token、冷却和消费使用 MySQL。邮箱验证与图形验证码不能保证一人一号。
