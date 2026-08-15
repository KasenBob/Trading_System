"""AI 分析服务（DeepSeek，OpenAI 兼容接口）"""

import requests

from config import settings


def analyze_stocks(stocks: list[dict]) -> str:
    """对多因子选股结果做 AI 分析，返回分析文本"""
    if not settings.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DeepSeek API Key")

    lines = []
    for i, s in enumerate(stocks, 1):
        lines.append(
            f"{i}. {s.get('name')}({s.get('code')}) 类型:{s.get('type', 'stock')} "
            f"行业:{s.get('industry') or '-'} PE:{s.get('pe')} PB:{s.get('pb')} "
            f"ROE:{s.get('roe')}% EP:{s.get('ep')} 20日涨幅:{s.get('momentum')}% "
            f"总市值:{s.get('market_cap')}亿 综合得分:{s.get('total_score')}"
        )
    stocks_text = "\n".join(lines)

    system_prompt = (
        "你是一位专业的A股量化投资分析师，擅长结合多因子选股结果进行基本面与技术面综合分析。"
        "回答使用简体中文，简洁专业、分点清晰。"
    )
    user_prompt = (
        f"以下是通过多因子选股模型（EP盈利收益率、ROE、20日动量、小市值四个因子加权打分）"
        f"筛选出的股票列表：\n\n{stocks_text}\n\n"
        "请从以下角度分析：\n"
        "1. 整体评价：这批股票的整体质量与风格特征\n"
        "2. 个股点评：对每只股票做一句话点评（估值/盈利/动量/风险）\n"
        "3. 风险提示：需要注意的风险点\n"
        "4. 操作建议：结合综合得分给出配置建议\n\n"
        "注意：以上仅为模型筛选结果，不构成投资建议。"
    )

    resp = requests.post(
        f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]
