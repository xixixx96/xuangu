"""
企业微信机器人推送模块
"""

import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class WecomPusher:
    """企业微信群机器人推送"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_markdown(self, content: str) -> bool:
        """
        发送 Markdown 格式消息

        Args:
            content: Markdown 内容

        Returns:
            True 表示发送成功
        """
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        }

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") != 0:
                logger.error(f"企业微信推送失败: {result}")
                return False
            logger.info("企业微信推送成功")
            return True
        except requests.RequestException as e:
            logger.error(f"企业微信推送请求异常: {e}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"企业微信响应解析失败: {e}")
            return False

    def send_text(self, content: str, mentioned_list: Optional[list[str]] = None) -> bool:
        """发送纯文本消息"""
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }
        if mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") != 0:
                logger.error(f"企业微信推送失败: {result}")
                return False
            return True
        except Exception as e:
            logger.error(f"企业微信推送失败: {e}")
            return False

    def send_job_report(self, markdown: str) -> bool:
        """
        发送岗位日报。
        企业微信 Markdown 消息最大 4096 字符，超长自动分段。
        """
        MAX_LEN = 4000  # 留一些余量
        if len(markdown) <= MAX_LEN:
            return self.send_markdown(markdown)

        # 按 --- 分割符分条发送
        sections = markdown.split("\n---\n")
        header = sections[0]
        body_sections = sections[1:]

        # 先发第一条（含头部）
        chunk = header
        chunk_num = 1
        total_chunks = 1  # 后面会更新

        for section in body_sections:
            if len(chunk) + len(section) + 10 > MAX_LEN:
                if chunk_num == 1:
                    # 第一条还没写数量，估算一下
                    pass
                success = self.send_markdown(chunk)
                if not success:
                    return False
                chunk = section
                chunk_num += 1
            else:
                chunk += "\n---\n" + section

        # 发最后一条
        if chunk:
            success = self.send_markdown(chunk)
            if not success:
                return False

        logger.info(f"分 {chunk_num} 条消息发送完成")
        return True
