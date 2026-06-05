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

msg = """<font color="warning">**企业微信机器人接收消息配置**</font>

步骤:
1. 在手机上打开企业微信
2. 进入选股群聊 -> 右上角三个点 -> 群机器人
3. 点击你的选股机器人 -> 开启"接收消息"
4. 复制页面上显示的 Token 和 EncodingAESKey
5. 把这两个值发给我

然后我帮你在本地启动一个回调服务!
(需要你的电脑保持开机)"""

push_to_wecom_markdown(msg)
print('OK')
