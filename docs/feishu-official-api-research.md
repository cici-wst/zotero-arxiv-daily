# 飞书集成官方 API 核对记录

核对日期：2026-08-11。以下结论只依据飞书开放平台官方文档（`open.feishu.cn`）。本记录用于把 `zotero-arxiv-daily` 的每日通知改为飞书群通知，并把论文信息写入飞书多维表格。

## 1. 群自定义机器人 Webhook

官方指南：[自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)。

在目标群中依次进入“群设置 → 群机器人 → 添加机器人 → 自定义机器人”，创建后复制 Webhook。请求使用 `POST`，`Content-Type: application/json`，URL 形如：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/<token>
```

自定义机器人只向当前群单向推送消息，不具备访问企业数据的权限，也不支持回调交互事件。官方支持的通知类型包括文本、`post` 富文本和 `interactive` 卡片。富文本请求结构示例：

```json
{
  "msg_type": "post",
  "content": {
    "post": {
      "zh_cn": {
        "title": "今日 arXiv 推荐",
        "content": [[
          {"tag": "text", "text": "论文标题"},
          {"tag": "a", "text": "查看论文", "href": "https://arxiv.org/abs/..."}
        ]]
      }
    }
  }
}
```

卡片教程：[使用自定义机器人发送消息卡片](https://open.feishu.cn/document/feishu-cards/quick-start/send-message-cards-with-custom-bot?lang=zh-CN)。请求顶层使用 `msg_type: "interactive"`，卡片内容可使用卡片 JSON 或模板。自定义机器人限制：单租户单机器人约 100 次/分钟、5 次/秒；请求体不超过 20 KB。安全设置可选关键词、IP 白名单或签名；签名请求在 JSON 顶层附加 `timestamp`、`sign`，时间戳与当前时间差不能超过 1 小时。Webhook 应放在 GitHub Secret，不要写入仓库源码或日志。

## 2. 自建应用与 tenant_access_token

官方文档：[获取自建应用的 tenant_access_token](https://open.feishu.cn/document/ukTMukTMukTM/ukDNz4SO0MjL5QzM/auth-v3/auth/tenant_access_token_internal?lang=zh-CN)。

请求：

```http
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Content-Type: application/json
```

```json
{"app_id":"cli_xxx","app_secret":"xxx"}
```

响应包含 `tenant_access_token` 和 `expire`；有效期最长约 2 小时。调用多维表格 API 时使用：

```http
Authorization: Bearer <tenant_access_token>
```

应用权限申请流程见[申请 API 权限](https://open.feishu.cn/document/server-docs/application-scope/introduction?lang=zh-CN)：开发者后台 → 指定自建应用 → 开发配置 → 权限管理 → 开通权限。当前场景至少开通“新增记录”和“根据条件搜索记录”；也可申请范围更大的“查看、评论、编辑和管理多维表格”。权限文档说明，接口页面列出的多个权限通常是“满足任一”关系。需审核权限在创建版本、提交审核并由应用管理员通过后才正式生效。

## 3. 写入多维表格

官方接口：[新增记录](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create?lang=zh-CN)。

```http
POST https://open.feishu.cn/open-apis/bitable/v1/apps/:app_token/tables/:table_id/records
Authorization: Bearer <tenant_access_token>
Content-Type: application/json
```

```json
{
  "fields": {
    "标题": "论文标题",
    "论文链接": {"text": "打开论文", "link": "https://arxiv.org/abs/xxxx.xxxxx"},
    "摘要": "...",
    "相关度": 0.82
  }
}
```

批量接口见[批量新增记录](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_create?lang=zh-CN)，单次最多 1,000 条，支持 `client_token` 幂等。官方多维表格概述建议对同一表同时只进行一次写操作。

使用 `tenant_access_token` 前，应用必须是该多维表格的所有者或协作者；官方说明可通过“添加文档应用”把应用添加为协作者：[多维表格概述](https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview?lang=zh-CN)。如果开启高级权限，还要在目标多维表格的文档权限中把该应用加入并授予足以写入的管理/编辑权限，否则可能出现 403 或空结果。

## 4. 获取 app_token 与 table_id

同一篇[多维表格概述](https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview?lang=zh-CN)说明：

- 普通 `https://feishu.cn/base/<app_token>?table=<table_id>&view=<view_id>` URL 中，`<app_token>` 和 `<table_id>` 就是所需标识。
- 知识库中的 `https://feishu.cn/wiki/...` 多维表格需调用“获取知识空间节点信息”，当返回 `obj_type` 为 `bitable` 时，`obj_token` 是 `app_token`。
- 也可调用[列出数据表](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table/list?lang=zh-CN)获取 `table_id`。

## 5. 字段类型与按论文链接去重

多维表格字段是列；字段类型和值应按官方字段/API schema 传递：文本为字符串，数字为 number，单选为选项值，多选为选项值数组，日期为毫秒时间戳，复选框为布尔值，超链接为 `{ "text": "显示文本", "link": "https://..." }`。本项目只保留 `论文链接` 超链接字段，使用其 `link` 成员规范化后去重。

官方接口：[查询记录](https://open.feishu.cn/document/docs/bitable-v1/app-table-record/search?lang=zh-CN)。请求：

```http
POST https://open.feishu.cn/open-apis/bitable/v1/apps/:app_token/tables/:table_id/records/search?page_size=1
Authorization: Bearer <tenant_access_token>
Content-Type: application/json
```

```json
{
  "field_names": ["论文链接"]
}
```

查询单次最多 500 行，支持 `page_token` 分页。实现去重时读取每条记录的 `fields.论文链接.link`，规范化后与新论文 URL 集合比较。业务上要检查响应 JSON 的 `code == 0`，不能只看 HTTP 200。迁移时先用旧 `论文URL` 回填缺失的 `论文链接`，再部署新代码并验证，最后删除旧列。

## 6. GitHub Actions Secrets

飞书官方不规定 GitHub Secret 名称；以下是本项目实现所需的仓库侧 Secret 命名建议：

```text
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_APP_TOKEN
FEISHU_TABLE_ID
FEISHU_WEBHOOK_URL
```

若启用 Webhook 签名，再增加：

```text
FEISHU_WEBHOOK_SECRET
```

原项目已有的 `ZOTERO_ID`、`ZOTERO_KEY`、`SENDER`、`SENDER_PASSWORD`、`RECEIVER`、`OPENAI_API_KEY`、`OPENAI_API_BASE` 是否保留，取决于后续是否完全移除邮件发送；飞书集成本身不需要 SMTP Secret。
