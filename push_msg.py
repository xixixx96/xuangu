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

msg = """<font color="warning">**生成 SSH 密钥的方法**</font>

1. 打开 CMD 命令提示符
2. 粘贴执行:
> ssh-keygen -t ed25519 -C \"xixixx96@github.com\"
3. 提示\"Enter file in which to save the key\" 直接回车
4. 提示\"Enter passphrase\" 直接回车(不设密码)
5. 提示\"Enter same passphrase again\" 再回车

完成后，下面这条命令查看你的公钥:
> type %userprofile%\\.ssh\\id_ed25519.pub

把屏幕上的内容复制下来，发给我。"""

push_to_wecom_markdown(msg)
print('OK')
