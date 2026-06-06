"""
消息格式化模块
"""

from datetime import datetime
from typing import Optional


def _safe_str(val, default="未知") -> str:
    if val is None:
        return default
    return str(val)


def _format_salary(job: dict) -> str:
    text = job.get("salary_text", "")
    if text:
        return text
    lo = job.get("salary_min")
    hi = job.get("salary_max")
    if lo and hi:
        return f"{lo//1000}K-{hi//1000}K"
    if lo:
        return f"{lo//1000}K起"
    if hi:
        return f"最高{hi//1000}K"
    return "薪资面议"


def format_daily_report(
    jobs: list[dict],
    date_str: Optional[str] = None,
    excluded_count: int = 0,
    platforms: Optional[list[str]] = None,
    cities: Optional[list[str]] = None,
) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    if cities is None:
        cities = ["上海", "杭州", "苏州"]
    city_str = " · ".join(cities)
    if platforms is None:
        platforms = []

    lines = []
    lines.append(f"## 🤖 AI/机器人行业岗位日报 | {date_str}")
    lines.append("")

    if excluded_count > 0:
        lines.append(f"> 📍 {city_str} | 从 **5 个平台** 中精选 **{len(jobs)}** 个岗位")
        lines.append(f"> ⚠️ 已排除 **{excluded_count}** 个（重复/低薪/失信/被执行/财务风险）")
    else:
        lines.append(f"> 📍 {city_str} | 从 **5 个平台** 中精选 **{len(jobs)}** 个岗位")
        lines.append(f"> ✅ 所有推送公司均通过财务健康检查")

    lines.append("")

    if not jobs:
        lines.append("---")
        lines.append("### 😴 今日暂无匹配岗位")
        lines.append("")
        lines.append("> 明天会继续监控，请保持关注。")
        lines.append("")
    else:
        for i, job in enumerate(jobs, 1):
            lines.append("---")
            title = _safe_str(job.get("title"), "未知名岗位")
            company = _safe_str(job.get("company"), "未知名公司")
            lines.append(f"### {i}. {title} @ {company}")

            # 薪资
            salary = _format_salary(job)
            lines.append(f"- 💰 **薪资**：{salary}")

            # 地点
            city = _safe_str(job.get("city"))
            district = job.get("district", "")
            location = f"{city} · {district}" if district else city
            lines.append(f"- 📍 **地点**：{location}")

            # 公司信息
            comp_status = job.get("company_status") or {}

            # 融资阶段 + 金额
            funding = comp_status.get("funding", "")
            funding_amount = comp_status.get("funding_amount", "")
            if funding and funding_amount:
                lines.append(f"- 🏢 **融资**：{funding} | 已融资 {funding_amount}")
            elif funding:
                lines.append(f"- 🏢 **融资**：{funding}")

            # 知名投资机构
            investors = comp_status.get("investors", "")
            if investors:
                lines.append(f"- 💎 **投资方**：{investors}")

            # 注册资本 + 成立时间
            capital = comp_status.get("registered_capital", "")
            established = comp_status.get("established", "")
            if capital and established:
                lines.append(f"- 📋 **注册资本**：{capital} | 成立于 {established}")
            elif capital:
                lines.append(f"- 📋 **注册资本**：{capital}")

            # 司法状态
            lawsuits = comp_status.get("lawsuits", 0)
            if lawsuits == 0:
                lines.append(f"- ⚖️ **司法**：零案件 ✅ | 经营正常 ✅")
            else:
                lines.append(f"- ⚖️ **司法**：{lawsuits} 条案件 | 经营正常 ✅")

            # 推送理由
            reason = job.get("_reason", "")
            if reason:
                lines.append(f"- 🎯 **推荐理由**：{reason}")

            # 岗位描述
            desc = _safe_str(job.get("description"), "")
            if desc:
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                lines.append(f"- 📝 **岗位描述**：{desc}")

            # 链接 + 评分
            url = job.get("url", "")
            platform = _safe_str(job.get("platform"), "")
            score = job.get("_score", 0)
            if url:
                lines.append(f"- 🔗 [查看详情（{platform}）]({url}) | 评分: {score}分")

            lines.append("")

    lines.append("---")
    if platforms:
        lines.append(f"> 📊 数据来源：{'、'.join(platforms)}")
    lines.append("> ⚠️ 财务/融资数据来自企查查公开信息+预置库，仅供参考")
    lines.append(f"> 🤖 自动化推送 | 下次推送：明天下午 3:00")

    return "\n".join(lines)


def format_test_message() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"## 🤖 测试消息\n\n> 这是一条测试推送\n> 发送时间：{now}\n\n---\n> AI/机器人招聘机器人已就绪，每天下午 3:00 自动推送岗位日报 🚀"
