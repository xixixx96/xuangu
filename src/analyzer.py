"""
AI 分析模块 —— 支持 DeepSeek / Claude / OpenAI 多后端
"""

import logging

from config import (
    AI_PROVIDER,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from screener import Candidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位实战派A股量化分析师。你收到的每只股票都经过了严格的技术面+基本面量化筛选，默认具备交易价值。

你的任务不是质疑筛选结果，而是给出可执行的交易建议。

要求：
1. 每只股票分析控制在300字以内
2. 必须包含以下六个部分：
   - 基本面速览：列出PE、ROE、毛利率、净利润增速等核心指标
   - 机构观点：近期主要券商/机构对该股的评级及核心看法（如无则写"暂无覆盖"）
   - 利好因素：近期可能推动股价上涨的消息面因素（政策利好/业绩超预期/产品突破/资金流入等）
   - 驱动因素：技术面信号 + 资金面动向，说明为何当前入选
   - 利空风险：可能压制股价的因素（如无则写"暂无明显利空"）
   - 操作建议：按以下标准判断
     * 买入：基本面无硬伤 + 技术信号明确 + 无明显利空 → 给出仓位%（短线3%-8%，波段10%-20%）
     * 观望：基本面一般，或存在一项中等风险待观察
     * 回避：存在重大利空（财务造假/ST风险/大额减持/行业崩塌），如无则不要轻易给回避
3. 不要给出具体的买卖价格
4. 不要使用"强烈推荐""保证""一定"等绝对化用语
5. 结尾必须加上免责声明

输出格式（严格按此格式，每只股票一个段落）：
【股票代码 股票名称】
基本面：PE=... ROE=... 毛利率=... 净利增速=...
机构观点：...
利好因素：...
驱动因素：...
利空风险：...
操作建议：...
---
"""


def build_analysis_prompt(candidates: list[Candidate], strategy_name: str) -> str:
    """构建分析 prompt（与后端无关）"""
    strategy_labels = {
        "scalping": "短线交易（持仓1-5天），关注量价异动和短期趋势突破",
        "swing": "波段操作（持仓1-4周），关注均线趋势和MACD信号",
        "value": "价值投资（持仓3个月以上），关注基本面和估值水平",
    }

    label = strategy_labels.get(strategy_name, strategy_name)

    stock_sections = []
    for c in candidates:
        sections = [
            f"股票代码: {c.code}",
            f"名称: {c.name}",
            f"最新价: {c.close:.2f}",
            f"涨跌幅: {c.change_pct:.2f}%",
            f"筛选理由: {c.reason}",
        ]
        if c.indicators_summary:
            sections.append(f"技术指标:\n{c.indicators_summary}")
        if c.fundamentals:
            from fundamentals import format_fundamentals_summary
            sections.append(f"基本面:\n{format_fundamentals_summary(c.fundamentals)}")

        stock_sections.append("\n".join(sections))

    stocks_text = "\n\n---\n\n".join(stock_sections)

    return f"""请分析以下{label}策略筛选出的候选股票，给出你的专业判断。

**【重要】请尽可能搜索并结合以下信息进行分析：**
1. 近期机构研报评级（券商/基金/保险对该股的最新观点和目标方向）
2. 近一周该股的利好新闻（业绩预增、政策利好、产品突破、大单中标、北向资金加仓等）
3. 近一周该股的利空新闻（业绩预警、监管风险、行业负面、大股东减持、限售解禁等）
4. 当前市场热点板块和资金偏好

{stocks_text}

请按格式对每只股票进行分析。"""


# ============================================================
# 主入口
# ============================================================

def call_ai_analysis(candidates: list[Candidate], strategy_name: str) -> str:
    """统一入口"""
    if AI_PROVIDER == "deepseek":
        return _call_deepseek(candidates, strategy_name)
    elif AI_PROVIDER == "claude":
        return _call_claude(candidates, strategy_name)
    elif AI_PROVIDER == "openai":
        return _call_openai(candidates, strategy_name)
    else:
        logger.warning("未知 AI_PROVIDER=%s，使用 fallback", AI_PROVIDER)
        return _fallback_analysis(candidates, strategy_name)


def _call_deepseek(candidates: list[Candidate], strategy_name: str) -> str:
    if not DEEPSEEK_API_KEY:
        logger.warning("未配置 DEEPSEEK_API_KEY")
        return _fallback_analysis(candidates, strategy_name)
    prompt = build_analysis_prompt(candidates, strategy_name)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        result = response.choices[0].message.content
        usage = response.usage
        logger.info("DeepSeek OK (%s) in=%d out=%d", strategy_name,
                     usage.prompt_tokens if usage else 0,
                     usage.completion_tokens if usage else 0)
        return result
    except ImportError:
        return _fallback_analysis(candidates, strategy_name)
    except Exception:
        logger.exception("DeepSeek 失败")
        return _fallback_analysis(candidates, strategy_name)


def _call_claude(candidates: list[Candidate], strategy_name: str) -> str:
    if not ANTHROPIC_API_KEY:
        return _fallback_analysis(candidates, strategy_name)
    prompt = build_analysis_prompt(candidates, strategy_name)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.content[0].text
        return result
    except ImportError:
        return _fallback_analysis(candidates, strategy_name)
    except Exception:
        logger.exception("Claude 失败")
        return _fallback_analysis(candidates, strategy_name)


def _call_openai(candidates: list[Candidate], strategy_name: str) -> str:
    if not OPENAI_API_KEY:
        return _fallback_analysis(candidates, strategy_name)
    prompt = build_analysis_prompt(candidates, strategy_name)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000, temperature=0.3,
        )
        return response.choices[0].message.content
    except ImportError:
        return _fallback_analysis(candidates, strategy_name)
    except Exception:
        logger.exception("OpenAI 失败")
        return _fallback_analysis(candidates, strategy_name)


def _fallback_analysis(candidates: list[Candidate], strategy_name: str) -> str:
    strategy_labels = {"scalping": "短线交易", "swing": "波段操作", "value": "价值投资"}
    label = strategy_labels.get(strategy_name, strategy_name)
    lines = [f"【{label}选股建议】（量化筛选，仅供参考）\n"]
    for c in candidates:
        lines.append(f"【{c.code} {c.name}】")
        lines.append(f"基本面：{c.reason}")
        lines.append("机构观点：暂无覆盖")
        lines.append("利好因素：技术面信号偏多")
        lines.append(f"驱动因素：{c.reason}")
        lines.append("利空风险：市场整体波动风险")
        lines.append("操作建议：请结合自身判断，注意风险控制")
        lines.append("---\n")
    lines.append("⚠️ 以上为量化模型筛选结果，不构成投资建议。股市有风险，投资需谨慎。")
    return "\n".join(lines)


call_claude_analysis = call_ai_analysis
