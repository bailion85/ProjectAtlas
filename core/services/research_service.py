from core.services.openai_service import OpenAIService


class ResearchService:

    def __init__(self):

        self.ai = OpenAIService()

    def build_report(self, stock, financial):

        prompt = f"""
You are Atlas, the Chief Investment Officer.

Your job is NOT to invent facts.

You must ONLY use the financial evidence provided.

Company:
{stock['name']}

Ticker:
{stock['symbol']}

Industry:
{stock['industry']}

Sector:
{stock['sector']}

Current Price:
{stock['price']}

Financial Score:
{financial.overall_score}/100

Strengths:
{chr(10).join(financial.strengths)}

Weaknesses:
{chr(10).join(financial.weaknesses)}

Reasoning:
{financial.reasoning}

Metrics:
{financial.metrics}

Write a professional investment report with the following sections:

1. Executive Summary

2. Financial Assessment

3. Strengths

4. Weaknesses

5. Risks

6. Overall Opinion

Do not make up numbers.

Do not mention information not provided.

Write like a professional equity research analyst.
"""

        return self.ai.ask(prompt)