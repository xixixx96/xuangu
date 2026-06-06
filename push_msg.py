"""向企业微信推送自定义消息"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open(r'C:\Users\xixixx96\Claude\xuangu\.env', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()
sys.path.insert(0, r'C:\Users\xixixx96\Claude\xuangu\src')
from push_wechat import push_to_wecom_markdown

msg = """<font color="warning">**怎么验证 GitHub Actions 是否正常**</font>

检查地址: https://github.com/xixixx96/skills-introduction-to-github/actions

你应该能看到一个名叫"每日选股推送"的 workflow。

<font color="info">**现在检查:**</font>
>1. 点进去，看看有没有运行记录（Run）
>2. 如果没有，说明 cron 定时还没到（周一至五 8:30）
>3. 可以手动测试: 点"Run workflow" -> 选 mode: all -> 点 Run

如果 workflow 列表里没有任何叫"每日选股推送"的名称:
>说明 .github/workflows/daily-pick.yml 没有被 GitHub 识别
>需要检查文件名和目录名是否正确"""

push_to_wecom_markdown(msg)
print('OK')
