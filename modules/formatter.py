"""
消息格式化模块
将岗位数据转换为企业微信 Markdown 格式的日报
"""

from datetime import datetime
from typing import Optional


def _safe_str(val, default="未知") -> str:
    """安全转字符串"""
    if val is None:
        return default
    return str(val)


def _format_salary(job: dict) -> str:
    """格式化薪资"""
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


def _format_company_status(status: Optional[dict]) -> str:
    """格式化公司财务状态"""
    if status is None:
        return "⏳ 财务状态：待查询"

    excluded = status.get("excluded", False)
    if excluded:
        return f"❌ 财务风险：{status.get('reason', '未知风险')}"

    parts = []
    lawsuits = status.get("lawsuits", 0)
    abnormal = status.get("abnormal", False)
    zhixing = status.get("zhixing", False)
    dishonesty = status.get("dishonesty", False)

    if lawsuits > 0:
        parts.append(f"司法案件 {lawsuits} 条")
    else:
        parts.append("司法案件 0 条")

    if zhixing:
        parts.append("⚠️被执行人")
    if dishonesty:
        parts.append("⚠️失信")
    if abnormal:
        parts.append("⚠️经营异常")

    if len(parts) == 1:
        parts.append("经营正常 ✅")

    return " | ".join(parts)


def format_daily_report(
    jobs: list[dict],
    date_str: Optional[str] = None,
    excluded_count: int = 0,
    platforms: Optional[list[str]] = None,
    cities: Optional[list[str]] = None,
) -> str:
    """
    生成岗位日报 Markdown

    Args:
        jobs: 岗位列表（需含 company_status 字段）
        date_str: 日期字符串
        excluded_count: 被财务检查排除的公司/岗位数
        platforms: 数据来源平台列表
        cities: 目标城市列表

    Returns:
        Markdown 格式的日报内容
    """
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
        lines.append(f"> 📍 {city_str} | 今日筛选到 **{len(jobs)}** 个匹配岗位")
        lines.append(f"> ⚠️ 已排除财务风险公司岗位 **{excluded_count}** 个")
    else:
        lines.append(f"> 📍 {city_str} | 今日筛选到 **{len(jobs)}** 个匹配岗位")
        lines.append(f"> ✅ 所有公司均通过财务健康检查")

    lines.append("")

    if not jobs:
        lines.append("---")
        lines.append("### 😴 今日暂无匹配岗位")
        lines.append("")
        lines.append("> 可能是因为：今日未发布新岗位，或所有新岗位均未通过财务检查。")
        lines.append("> 明天会继续监控，请保持关注。")
        lines.append("")
    else:
        for i, job in enumerate(jobs, 1):
            lines.append("---")
            title = _safe_str(job.get("title"), "未知名岗位")
            company = _safe_str(job.get("company"), "未知名公司")
            lines.append(f"### {i}. {title} @ {company}")

            salary = _format_salary(job)
            lines.append(f"- 💰 **薪资**：{salary}")

            city = _safe_str(job.get("city"))
            district = job.get("district", "")
            location = f"{city} · {district}" if district else city
            lines.append(f"- 📍 **地点**：{location}")

            # 公司信息
            company_info = _safe_str(job.get("company_info"), "")
            if company_info:
                lines.append(f"- 🏢 **公司信息**：{company_info}")

            # 财务状态
            comp_status = job.get("company_status")
            status_line = _format_company_status(comp_status)
            lines.append(f"- {status_line}")

            # 岗位描述
            desc = _safe_str(job.get("description"), "")
            if desc:
                # 截取前 200 字
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                lines.append(f"- 📝 **岗位描述**：{desc}")

            # 链接
            url = job.get("url", "")
            platform = _safe_str(job.get("platform"), "")
            if url:
                lines.append(f"- 🔗 [查看详情（{platform}）]({url})")

            lines.append("")

    # 页脚
    lines.append("---")
    if platforms:
        platform_list = "、".join(platforms)
        lines.append(f"> 📊 数据来源：{platform_list}")
    lines.append("> ⚠️ 财务数据来自企查查公开信息，仅供参考")
    lines.append(f"> 🤖 自动化推送 | 下次推送：明天下午 3:00")

    return "\n".join(lines)


def format_test_message() -> str:
    """生成测试消息"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"## 🤖 测试消息\n\n> 这是一条测试推送\n> 发送时间：{now}\n\n---\n> AI/机器人招聘机器人已就绪，每天下午 3:00 自动推送岗位日报 🚀"
