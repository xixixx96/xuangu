"""
推送模块 —— 企业微信群机器人 Markdown 消息（带颜色和排版）
"""

import logging
import os
import re
from datetime import datetime

import requests

from config import WECHAT_APP_ID, WECHAT_APP_SECRET, WECHAT_TEMPLATE_ID, WECHAT_OPENIDS

logger = logging.getLogger(__name__)

# ==================== 企业微信群机器人 Webhook ====================

_WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=c0fdbe26-a140-481c-afaf-edc175b570dd"


def push_to_wecom_markdown(full_text: str) -> bool:
    """通过企业微信群机器人发送 Markdown 消息"""
    try:
        r = requests.post(
            _WECOM_WEBHOOK,
            json={"msgtype": "markdown", "markdown": {"content": full_text}},
            timeout=30,
        )
        result = r.json()
        if result.get("errcode") == 0:
            logger.info("企业微信推送成功 (webhook key=%s...)", _WECOM_WEBHOOK.split("key=")[-1][:8])
            return True
        else:
            logger.error("企业微信推送失败: errcode=%s errmsg=%s", result.get("errcode"), result.get("errmsg"))
            return False
    except Exception:
        logger.exception("企业微信推送网络异常")
        return False


# ============================================================
# AI 分析文本 → 美化 Markdown
# ============================================================

def _beautify_analysis(raw: str) -> str:
    """
    将 AI 原始分析文本转换为带颜色和粗体的企业微信 Markdown
    颜色方案：
      股票代码 - 蓝色(info)加粗
      股票名称 - 蓝色(info)加粗
      字段标签(机构观点/利好因素/操作建议) - 橙色(warning)加粗
      正文 - 不加粗
      买入 - 绿色(info)加粗
      观望 - 灰色(comment)加粗
    """
    lines = raw.split("\n")
    out = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue

        # 股票标题行 【代码 名称】 — 用引用块+加大字号(# )模拟大号字体
        if stripped.startswith("【"):
            m = re.match(r"【(.+?) (.+)】", stripped)
            if m:
                code = m.group(1)
                name = m.group(2)
                out.append(f'> **<font color="info"># {code} {name}</font>**')
            else:
                out.append(f'> **<font color="info"># {stripped}</font>**')
            continue

        # 分隔线
        if stripped == "---":
            out.append("---")
            continue

        # 字段行：标签加粗着色，正文不处理
        if "：" in stripped:
            field, _, value = stripped.partition("：")

            # 字段标签颜色
            field_colors = {
                "基本面": "warning",
                "机构观点": "warning",
                "利好因素": "warning",
                "驱动因素": "warning",
                "利空风险": "comment",
                "操作建议": "warning",
            }
            color = field_colors.get(field.strip())

            # 操作建议关键词着色
            if field.strip() == "操作建议":
                value = value.replace("买入", '<font color="info">**买入**</font>')
                value = value.replace("观望", '<font color="comment">**观望**</font>')
                value = value.replace("回避", '<font color="warning">**回避**</font>')

            if color:
                out.append(f'<font color="{color}">**{field}：**</font>{value}')
            else:
                out.append(f'**{field}：**{value}')
            continue

        # 其他行保持原样
        out.append(stripped)

    return "\n".join(out)


# ============================================================
# 统一推送入口
# ============================================================

def push_strategy_pick(
    strategy_label: str,
    strategy_emoji: str,
    candidates: list,
    ai_analysis: str,
) -> int:
    """推送一个策略的选股建议到企业微信群"""
    if not candidates:
        logger.info("%s 策略无候选标的", strategy_label)
        return 0

    now = datetime.now()
    date_str = now.strftime("%m/%d")

    # 美化 AI 分析
    beautified = _beautify_analysis(ai_analysis)

    # 策略颜色
    strategy_colors = {
        "短线交易": "warning",
        "短线交易(盘中)": "warning",
        "波段操作": "info",
        "价值投资": "comment",
    }
    sc = strategy_colors.get(strategy_label, "info")

    # 组装完整消息
    full_text = (
        f'**<font color="{sc}">{strategy_emoji} {strategy_label} 选股建议 | {date_str}</font>**\n'
        f"{beautified}\n\n"
        f'<font color="comment">---\n'
        f'⚠️ 以上分析由AI生成，仅供参考，不构成投资建议</font>'
    )

    logger.info("推送内容长度: %d 字", len(full_text))

    ok = push_to_wecom_markdown(full_text)
    return 1 if ok else 0
