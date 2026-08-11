# 飞书论文推荐交付设计

## 目标

将 `zotero-arxiv-daily` 从 SMTP 邮件交付改为飞书交付：每日推荐论文写入飞书多维表格，并通过飞书群自定义机器人发送摘要通知。邮件发送功能彻底移除。

## 范围

- 保留现有 Zotero 获取、论文检索、排序和 LLM 摘要流程。
- 新增飞书自建应用客户端，使用 `FEISHU_APP_ID` 与 `FEISHU_APP_SECRET` 获取 `tenant_access_token`。
- 使用 `FEISHU_APP_TOKEN` 与 `FEISHU_TABLE_ID` 查询多维表格中的 `论文URL`，按 URL 去重，并批量新增不存在的论文。
- 使用 `FEISHU_WEBHOOK_URL` 向群自定义机器人发送中文交互卡片通知。
- 移除 SMTP 发送代码、邮箱配置和 GitHub Actions 中的邮箱环境变量。
- 保留 `executor.send_empty` 语义：为 false 且检索不到论文时不写表、不发群消息；为 true 时发送“今日无新论文”通知。

## 配置与字段映射

GitHub Actions Secrets：

```text
ZOTERO_ID
ZOTERO_KEY
OPENAI_API_KEY
OPENAI_API_BASE
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_WEBHOOK_URL
```

Repository Variables：

```text
CUSTOM_CONFIG
```

`FEISHU_APP_TOKEN` 和 `FEISHU_TABLE_ID` 不是凭据，直接放在 `CUSTOM_CONFIG` 的 `feishu` 配置中：

```yaml
feishu:
  app_id: ${oc.env:FEISHU_APP_ID}
  app_secret: ${oc.env:FEISHU_APP_SECRET}
  app_token: VifgbgBseaSpyIsCpH8cIlqVnub
  table_id: tblphxHROAQPFf4k
  webhook_url: ${oc.env:FEISHU_WEBHOOK_URL}
```

`FeishuClient` 只从 Hydra 组合后的 `config.feishu` 接收这五项配置，不在客户端内直接读取环境变量。

论文字段映射：

| 多维表格字段 | `Paper` 来源 |
| --- | --- |
| 标题 | `title` |
| 论文URL | `url` |
| 论文链接 | `{text: "打开论文", link: url}` |
| 作者 | `authors` 用 `, ` 拼接 |
| 摘要 | `abstract` |
| TLDR | `tldr` |
| 作者单位 | `affiliations` 用 `, ` 拼接 |
| 来源 | `source` |
| 分类 | 由 URL/来源数据提供的分类；当前 Paper 无分类时不填 |
| 相关度 | `score` |
| 发布日期 | 当前 Paper 无统一发布日期字段时不填 |
| 推荐日期 | 当前日期的毫秒时间戳 |
| 代码链接 | 当前 Paper 无代码链接字段时不填 |

字段类型固定为：`标题`、`论文URL`、`作者`、`摘要`、`TLDR`、`作者单位` 为文本；`论文链接`、`代码链接` 为超链接对象；`来源` 为单选；`分类` 为多选；`相关度` 为数字；`发布日期`、`推荐日期` 为毫秒时间戳日期。`推荐日期` 使用 `Asia/Shanghai` 当天零点的毫秒时间戳。客户端在写入前读取字段元数据，字段缺失或类型不符时直接报错。

## URL 规范化

- 协议与主机名转为小写，删除 query、fragment 和路径末尾斜杠。
- arXiv 的 `/abs/`、`/pdf/`、`/html/`、`/e-print/` 地址统一为 `https://arxiv.org/abs/<paper-id>`；删除 `.pdf` 和末尾版本号 `vN`。
- bioRxiv、medRxiv 的 `/content/<doi>vN...` 地址统一为 `https://doi.org/<doi>`，版本号和 `.full.pdf` 不参与去重。
- 其他来源保留规范化后的路径，不修改路径大小写。

## 模块设计

新增 `src/zotero_arxiv_daily/feishu.py`：

- `FeishuClient`：封装令牌获取、记录查询、批量创建和群机器人发送。
- 所有 HTTP 请求使用现有项目依赖 `openai` 不适合承载飞书 API，因此新增轻量 `requests` 依赖，设置明确超时并在非零飞书错误码时抛出异常。
- 客户端接受配置对象和可注入 HTTP session，便于单元测试；不在模块中读取或打印 Secret。
- 群消息正文使用论文标题、TLDR 和链接。按序列化后的请求体大小拆分成多条卡片，确保每个请求满足飞书 20 KB 限制。若单篇论文仍超过限制，只截断通知中的 TLDR，并追加“完整内容见多维表格”，同时输出不含正文和凭据的 warning；表格内容不截断。
- 现有 `executor.max_paper_num` 保持不变，它仍决定整个推荐管线最多处理多少篇论文；消息层不再增加额外数量上限。

修改 `Executor`：

- 初始化 `FeishuClient` 替代 SMTP 相关配置。
- 将排序后的论文转换为字段字典，一次分页读取现有 `论文URL`，再批量写入缺失记录。
- 写表后为本次检索到的全部论文发送群通知，卡片同时显示“推荐数量”和“新写入数量”。表格写入幂等；群消息采用至少一次语义，失败重跑时允许重复通知以避免丢失通知。
- 批量新增按飞书单次 1,000 条记录的上限分块；跨批次失败时抛出错误，重跑依赖 URL 去重跳过已成功批次。
- 任何 API 错误都显式抛出并让 Action 失败，不做静默降级。

## GitHub Actions 与文档

- `.github/workflows/main.yml`、`.github/workflows/test.yml` 注入飞书 Secrets，移除 `SENDER`、`RECEIVER`、`SENDER_PASSWORD`。
- `config/base.yaml`、`config/custom.yaml` 改为 `feishu` 配置，删除 `email` 配置。
- `README.md` 改写部署步骤，说明创建飞书自建应用、权限、表格协作者、群机器人和 Secrets。

## 错误处理

- HTTP 非 2xx、飞书 JSON `code != 0`、缺少必填响应字段都抛出带接口上下文的异常。
- 不捕获后吞掉网络/API 错误；GitHub Actions 日志只记录状态和数量，不记录 Token、Secret 或 Webhook 完整 URL。
- 查询去重使用规范化后的精确 URL；查询结果分页时继续读取，直到 `has_more` 为 false。
- 写入前校验目标表字段名称与字段类型，避免把超链接、数字或日期以错误结构写入。

## 测试策略

- 先为字段映射、URL 规范化、消息分片、令牌请求、查询分页、批量写入和 Webhook 成功/失败分别编写失败测试。
- 使用本地 HTTP session stub，不访问真实飞书账户。
- 更新 Executor 集成测试，断言去重后只写入新论文并发送一次群通知。
- 覆盖全量重复、单篇通知超过 20 KB、超过 1,000 条的分块写入、跨批次失败重跑和表格字段缺失/类型错误。
- 运行 `uv run pytest` 和 Python 编译检查；完成前核对 Git diff 与工作流引用。
