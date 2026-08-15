<p align="center">
  <a href="" rel="noopener">
 <img width=200px height=200px src="assets/logo.svg" alt="logo"></a>
</p>

<h3 align="center">Zotero-arXiv-Daily</h3>

<div align="center">

  [![Status](https://img.shields.io/badge/status-active-success.svg)]()
  ![Stars](https://img.shields.io/github/stars/TideDra/zotero-arxiv-daily?style=flat)
  [![GitHub Issues](https://img.shields.io/github/issues/TideDra/zotero-arxiv-daily)](https://github.com/TideDra/zotero-arxiv-daily/issues)
  [![GitHub Pull Requests](https://img.shields.io/github/issues-pr/TideDra/zotero-arxiv-daily)](https://github.com/TideDra/zotero-arxiv-daily/pulls)
  [![License](https://img.shields.io/github/license/TideDra/zotero-arxiv-daily)](/LICENSE)
  [<img src="https://api.gitsponsors.com/api/badge/img?id=893025857" height="20">](https://api.gitsponsors.com/api/badge/link?p=PKMtRut1dWWuC1oFdJweyDSvJg454/GkdIx4IinvBblaX2AY4rQ7FYKAK1ZjApoiNhYEeduIEhfeZVIwoIVlvcwdJXVFD2nV2EE5j6lYXaT/RHrcsQbFl3aKe1F3hliP26OMayXOoZVDidl05wj+yg==)

</div>

---

<p align="center"> Recommend new arxiv papers of your interest daily according to your Zotero library.
    <br> 
</p>

> [!IMPORTANT]
> Please keep an eye on this repo, and merge your forked repo in time when there is any update of this upstream, in order to enjoy new features and fix found bugs.

## 🧐 About <a name = "about"></a>

> Track new scientific researches of your interest by just forking (and staring) this repo!😊

*Zotero-arXiv-Daily* finds papers that may attract you based on the context of your Zotero library, stores the recommendations in Feishu Bitable, and posts a summary card to a Feishu group. It can be deployed as a GitHub Actions workflow with **zero cost**, **no installation**, and a small set of repository secrets for daily **automatic** delivery.

## ✨ Features
- Totally free! All the calculation can be done in the Github Action runner locally within its quota (for public repo).
- AI-generated TL;DR for you to quickly pick up target papers.
- Paper links, metadata, and TLDRs are persisted in Feishu Bitable.
- Feishu group cards link directly to the recommended papers and the Bitable.
- Canonical paper URLs prevent duplicate Bitable records across repeated workflow runs.
- List of papers sorted by relevance with your recent research interest.
- Fast deployment via fork this repo and set environment variables in the Github Action Page.
- Support LLM API for generating TL;DR of papers.
- Ignore unwanted Zotero papers using a list of glob patterns.
- Support multiple sources of papers to retrieve:
  - arxiv
  - biorxiv
  - medrxiv

## 📷 Screenshot
![screenshot](./assets/screenshot.png)

## 🚀 Usage
### Quick Start
1. Fork (and star😘) this repo.
![fork](./assets/fork.png)

2. Prepare Feishu.

   - Create a Feishu self-built app, grant the Bitable read/write permissions required to list fields, search records, and batch-create records, then publish the app version.
   - Open the target Bitable and add the self-built app as a collaborator with edit permission.
   - In the target Feishu group, add a **Custom Bot** and copy its Webhook URL.
   - This fork is configured for the Bitable at `https://my.feishu.cn/base/VifgbgBseaSpyIsCpH8cIlqVnub`, table `论文推荐`.

   The table schema is validated at runtime and must contain these fields with the exact types:

   | Field | Feishu type |
   | :--- | :--- |
   | 标题、作者、摘要、TLDR | Text |
   | 代码链接、论文链接 | URL |
   | 分类 | Multiple select |
   | 相关度 | Number |
   | 发布日期、推荐日期 | Date |

   `TLDR` is a one-sentence AI summary of the paper's core idea. Keep `论文链接`
   as the clickable Feishu hyperlink and the canonical URL used for deduplication.
   Before deploying this change, backfill `论文链接` from valid old `论文URL`
   values, repair or delete rows missing both values, run the new workflow once,
   and then delete the physical `论文URL` column.

3. Set GitHub Actions secrets.
![secrets](./assets/secrets.png)

Below are all the secrets you need to set. They are invisible to anyone including you once they are set, for security.

| Key |Description | Example |
| :---  | :---  | :--- |
| ZOTERO_ID  | User ID of your Zotero account. **User ID is not your username, but a sequence of numbers**Get your ID from [here](https://www.zotero.org/settings/security). You can find it at the position shown in this [screenshot](https://github.com/TideDra/zotero-arxiv-daily/blob/main/assets/userid.png). | 12345678  |
| ZOTERO_KEY | An Zotero API key with read access. Get a key from [here](https://www.zotero.org/settings/security).  | AB5tZ877P2j7Sm2Mragq041H   |
| OPENAI_API_KEY | API Key when using the API to access LLMs. You can get FREE API for using advanced open source LLMs in [SiliconFlow](https://cloud.siliconflow.cn/i/b3XhBRAm). | sk-xxx |
| OPENAI_API_BASE | API URL when using the API to access LLMs. | https://api.siliconflow.cn/v1 |
| FEISHU_APP_ID | App ID of the published Feishu self-built application. | cli_xxx |
| FEISHU_APP_SECRET | App Secret of the Feishu self-built application. | Keep this value only in GitHub Secrets |
| FEISHU_WEBHOOK_URL | Webhook URL of the Custom Bot in the target Feishu group. | `https://open.feishu.cn/open-apis/bot/v2/hook/...` |

The SMTP secrets `SENDER`, `SENDER_PASSWORD`, and `RECEIVER` are no longer used.

Then you should also set a public variable `CUSTOM_CONFIG` for your custom configuration.
![vars](./assets/repo_var.png)
![custom_config](./assets/config_var.png)
Paste the following content into the value of `CUSTOM_CONFIG` variable:
```yaml
zotero:
  user_id: ${oc.env:ZOTERO_ID}
  api_key: ${oc.env:ZOTERO_KEY}
  include_path: null # Or e.g. ["2026/survey/**", "2026/reading-group/**"]

feishu:
  app_id: ${oc.env:FEISHU_APP_ID}
  app_secret: ${oc.env:FEISHU_APP_SECRET}
  app_token: VifgbgBseaSpyIsCpH8cIlqVnub
  table_id: tblphxHROAQPFf4k
  webhook_url: ${oc.env:FEISHU_WEBHOOK_URL}

llm:
  api:
    key: ${oc.env:OPENAI_API_KEY}
    base_url: ${oc.env:OPENAI_API_BASE}
  generation_kwargs:
    model: gpt-4o-mini

source:
  arxiv:
    category: ["cs.AI","cs.CV","cs.LG","cs.CL"]
    include_cross_list: false # Set to true to include arXiv cross-list papers in these categories.

executor:
  debug: ${oc.env:DEBUG,null}
  source: ['arxiv']
```
Set `source.arxiv.include_cross_list: true` if you want cross-listed papers included.
>[!NOTE]
> `${oc.env:XXX,yyy}` means the value of the environment variable `XXX`. If the variable is not set, the default value `yyy` will be used.

Here is the full configuration, `???` means the value must be filled in:
```yaml
zotero:
  user_id: ??? # User ID of your Zotero account.
  api_key: ??? # An Zotero API key with read access.
  include_path: null # A list of glob patterns marking the Zotero collections that should be included. Example: ["2026/survey/**", "2026/reading-group/**"]

source:
  arxiv:
    category: null # The categories of target arxiv papers. Find the abbr of your research area from [here](https://arxiv.org/category_taxonomy). Example: ["cs.AI","cs.CV","cs.LG","cs.CL"]
    include_cross_list: false # Whether to include arXiv cross-list papers in subscribed categories. Example: true
  biorxiv:
    category: null # The categories of target biorxiv papers. Find categories from [here](https://www.biorxiv.org/). Example: ["biochemistry","animal behavior and cognition"]
  medrxiv:
    category: null # The categories of target medrxiv papers. Find categories from [here](https://www.medrxiv.org/) Example: ["psychiatry and clinical psychology", "neurology"]

feishu:
  app_id: ??? # App ID of the published Feishu self-built application.
  app_secret: ??? # App Secret of the Feishu self-built application.
  app_token: ??? # Bitable app token from the table URL.
  table_id: ??? # Bitable table ID from the table URL.
  webhook_url: ??? # Webhook URL of the Custom Bot in the target Feishu group.

llm:
  api:
    key: ??? # API Key of your LLM API. Example: sk-xxx
    base_url: ??? # API URL of your LLM API. Example: https://api.openai.com/v1
  generation_kwargs:
  # Arguments for the LLM API. See [here](https://platform.openai.com/docs/api-reference/chat/create) for more details.
    max_tokens: 16384
    model: ???
  language: English # Preferred language for the TL;DR. Example: English

reranker:
  local:
    model: jinaai/jina-embeddings-v5-text-nano # The Hugging Face model name of the local embedding model. Example: jinaai/jina-embeddings-v5-text-nano
    encode_kwargs:
    # The kwargs for the encode method of the local embedding model. Details see [here](https://www.sbert.net/docs/package_reference/SentenceTransformer.html#sentence_transformers.SentenceTransformer.encode)
      task: retrieval
      prompt_name: document
  api:
    key: null # API Key of your embedding model API. Example: sk-xxx
    base_url: null # API URL of your embedding model API. Example: https://api.openai.com/v1
    model: null # The model name of the embedding model. Example: text-embedding-3-large
    batch_size: null # The batch size for embedding API requests. Adjust to match your provider's limit. Example: 64

executor:
  debug: false # Whether to use debug mode. Example: true
  send_empty: false # Whether to send an empty Feishu notification even if no new papers today. Example: true
  max_paper_num: 100 # The maximum number of papers delivered to Feishu. Example: 100
  source: ??? # The sources of papers to retrieve. Example: ['arxiv','biorxiv','medrxiv']
  reranker: local # The reranker to use. Example: 'local' or 'api'
```

That's all! Now you can test the workflow by manually triggering it:
![test](./assets/test.png)

> [!NOTE]
> The `Test Feishu delivery` workflow is the debug version of the main workflow. The main workflow runs daily and retrieves papers released on the previous day. There may be no new arXiv papers on weekends and holidays, in which case the log reports `No new papers found`.

After it finishes, check the Actions log, the `论文推荐` Bitable, and the Feishu group containing the Custom Bot.

By default, the main workflow runs at 22:00 UTC, which is 06:00 the next day in Beijing time. You can change this time by editing `.github/workflows/main.yml`.

Each run normalizes arXiv and bioRxiv/medRxiv URLs before comparing them with existing Bitable records. Re-running a workflow therefore does not insert the same paper again. Group Webhook delivery is at-least-once: a manual rerun can post another group card even when all table records already exist.

### Local Running
Supported by [uv](https://github.com/astral-sh/uv), this workflow can easily run on your local device if uv is installed:
```bash
# set all the environment variables
# export ZOTERO_ID=xxxx
# ...
cd zotero-arxiv-daily
uv run main.py
```

## 🚀 Sync with the latest version
This project is in active development. You can subscribe this repo via `Watch` so that you can be notified once we publish new release.

![Watch](./assets/subscribe_release.png)


## 📖 How it works
*Zotero-arXiv-Daily* retrieves papers from your Zotero library and papers released on the previous day. It calculates embedding similarity, reranks candidates, and generates one-sentence TLDRs with an OpenAI-compatible API. Before delivery, it validates the 11-field Feishu Bitable schema, canonicalizes paper URLs, skips records already present in the table, batch-creates new records, and finally posts one or more size-limited interactive cards to the Feishu group.

## 📌 Limitations
- The recommendation algorithm is very simple, it may not accurately reflect your interest. Welcome better ideas for improving the algorithm!
- High `MAX_PAPER_NUM` can lead the execution time exceed the limitation of Github Action runner (6h per execution for public repo, and 2000 mins per month for private repo). Commonly, the quota given to public repo is definitely enough for individual use. If you have special requirements, you can deploy the workflow in your own server, or use a self-hosted Github Action runner, or pay for the exceeded execution time.


## 📃 License
Distributed under the AGPLv3 License. See `LICENSE` for detail.

## ❤️ Acknowledgement
- [pyzotero](https://github.com/urschrei/pyzotero)
- [arxiv](https://github.com/lukasschwab/arxiv.py)
- [sentence_transformers](https://github.com/UKPLab/sentence-transformers)

## ☕ Buy Me A Coffee
If you find this project helpful, welcome to sponsor me via WeChat or via [ko-fi](https://ko-fi.com/tidedra).
![wechat_qr](assets/wechat_sponsor.JPG)


## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TideDra/zotero-arxiv-daily&type=Date)](https://star-history.com/#TideDra/zotero-arxiv-daily&Date)
