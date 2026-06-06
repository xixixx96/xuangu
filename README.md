# 🤖 AI/机器人行业岗位日报推送机器人

每天下午 3:00 自动抓取主流招聘平台上的 AI、具身智能、机器人行业的**产品经理**和**解决方案工程师**岗位，经公司财务健康检查后推送至企业微信。

## 功能

- 🔍 **多平台抓取**：Boss直聘、拉勾网、猎聘、智联招聘、前程无忧（5大平台）
- 🏙️ **城市限定**：上海、杭州、苏州
- 💰 **薪资过滤**：仅推送月薪 ≥ 25K 的岗位
- 🛡️ **财务检查**：自动检查公司司法案件、被执行人、经营异常、失信等信息
- 📊 **智能去重**：同一岗位 30 天内不重复推送
- ⏰ **每日推送**：每天下午 3:00 通过 GitHub Actions 自动运行

## 项目结构

```
├── run.py                  # 主入口
├── config.py               # 配置文件
├── requirements.txt        # Python 依赖
├── scrapers/               # 爬虫模块
│   ├── base.py             # 基础爬虫类
│   ├── boss_zhipin.py      # Boss直聘
│   ├── lagou.py            # 拉勾网
│   ├── liepin.py           # 猎聘
│   ├── zhilian.py          # 智联招聘
│   └── job51.py            # 前程无忧
├── modules/                # 功能模块
│   ├── company_check.py    # 企查查财务检查
│   ├── storage.py          # 去重存储
│   ├── formatter.py        # 消息格式化
│   └── pusher.py           # 企业微信推送
├── .github/workflows/      # GitHub Actions
│   └── daily-push.yml
└── data/                   # 运行时数据
    ├── seen_jobs.json      # 已推送岗位记录
    └── company_cache.json  # 公司财务缓存
```

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（Boss直聘需要）
playwright install chromium

# 测试推送（验证企业微信 Webhook 是否正常）
python run.py --test

# 试运行（抓取但不推送）
python run.py --dry-run

# 完整运行
python run.py
```

### 配置 GitHub Actions

1. 将此仓库推送到 GitHub
2. GitHub Actions 会自动按 cron `0 7 * * *` 每天北京时间下午 3:00 运行
3. 也可以手动在 Actions 页面触发：`workflow_dispatch`

## 配置说明

编辑 `config.py` 可调整：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `TARGET_CITIES` | 目标城市 | 上海、杭州、苏州 |
| `MIN_SALARY` | 最低月薪（元） | 25000 |
| `JOB_KEYWORDS` | 搜索关键词 | AI产品经理、具身智能... |
| `MAX_PAGES_PER_PLATFORM` | 每个平台最大页数 | 3 |
| `QICHACHA_MAX_LAWSUITS` | 司法案件容忍上限 | 5 |
| `DEDUP_DAYS` | 去重窗口（天） | 30 |

## 企业微信消息格式

推送消息为 Markdown 格式，包含：
- 岗位名称 & 公司
- 薪资范围
- 工作地点
- 公司介绍
- 财务状态（司法案件、被执行人、经营异常等）
- 岗位描述摘要
- 原始链接

## 注意事项

- Boss直聘需要 Playwright 无头浏览器，GitHub Actions 已配置自动安装
- 企查查免费查询有频率限制，已实现 24 小时缓存机制
- 招聘平台可能偶尔反爬导致部分平台无数据，但不影响其他平台
- 企业微信 Markdown 消息限制 4096 字符，超长会自动分段发送

## 许可

MIT
