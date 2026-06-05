# A股 AI 选股每日推送

每个交易日自动筛选 A 股标的，结合 DeepSeek AI 深度分析，通过**企业微信群机器人**推送到手机。

## 推送策略

| 策略 | 频率 | 推送时间 | 持仓周期 |
|------|------|----------|---------|
| ⚡ 短线交易 | 每个交易日 | 早上 8:30 | 1-5 天 |
| 📈 波段操作 | 每个交易日 | 早上 8:30 | 1-4 周 |
| 💎 价值投资 | 每周一 | 早上 8:30 | 3 个月+ |

每种策略推荐 **2 只**标的，包含基本面、机构观点、利好利空因素等完整分析。

## 前置准备

### 1. 准备 DeepSeek API Key
注册 DeepSeek（https://platform.deepseek.com）获取 API Key。

### 2. 创建企业微信群机器人
- 在企业微信中创建一个群聊（至少 3 人，创建后可退出 2 人）
- 群设置 → 群机器人 → 添加 → 复制 Webhook URL
- Webhook 格式：`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx`

### 3. 本地配置
编辑项目根目录的 `.env` 文件：
```ini
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
```
并在 `src/push_wechat.py` 中更新 `_WECOM_WEBHOOK` 为你的 Webhook URL。

## 本地测试

```bash
pip install -r requirements.txt

# 所有策略
python src/main.py --mode all

# 仅每日短线+波段
python src/main.py --mode daily

# 仅价值策略
python src/main.py --mode value
```

## GitHub Actions 部署

在仓库 Settings → Secrets → Actions 中添加：

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |

定时触发：
- **周一至周五 8:30** → 短线 + 波段
- **周一 8:30** → 短线 + 波段 + 价值

## 免责声明

本项目选股建议由量化模型和 AI 自动生成，**仅供参考，不构成投资建议**。
股市有风险，投资需谨慎。
