from core.services.openai_service import OpenAIService


class ResearchService:

    def __init__(self):
        self.ai = OpenAIService()

    def analyze_stock(self, stock):

        prompt = f"""
You are Atlas, an AI investment analyst.

Analyze the following company.

Company: {stock["name"]}
Ticker: {stock["symbol"]}
Current Price: {stock["price"]}
Market Cap: {stock["market_cap"]}
P/E Ratio: {stock["pe_ratio"]}
Sector: {stock["sector"]}
Industry: {stock["industry"]}

Write a short investment summary that includes:

1. Strengths
2. Risks
3. Overall opinion

Keep it under 250 words.
"""

        return self.ai.ask(prompt)