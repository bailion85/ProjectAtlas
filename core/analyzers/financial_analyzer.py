from core.models.analysis_result import AnalysisResult


class FinancialAnalyzer:

    def analyze(self, stock):

        strengths = []
        weaknesses = []
        reasoning = {}
        category_scores = {}

        overall_score = 0

        # ----------------------------
        # Revenue Growth
        # ----------------------------

        revenue_score = 5
        revenue_growth = stock.get("revenue_growth")

        if revenue_growth is not None:

            if revenue_growth >= 0.15:
                revenue_score = 10
                strengths.append("Revenue is growing at an excellent rate.")
                reasoning["Revenue Growth"] = (
                    f"Revenue growth of {revenue_growth:.1%} indicates the "
                    "company continues expanding rapidly."
                )

            elif revenue_growth >= 0.05:
                revenue_score = 8
                strengths.append("Healthy revenue growth.")
                reasoning["Revenue Growth"] = (
                    f"Revenue growth of {revenue_growth:.1%} is healthy and "
                    "shows continued business expansion."
                )

            elif revenue_growth > 0:
                revenue_score = 6
                reasoning["Revenue Growth"] = (
                    "Revenue is growing, although slower than desired."
                )

            else:
                revenue_score = 2
                weaknesses.append("Revenue is shrinking.")
                reasoning["Revenue Growth"] = (
                    "Declining revenue is a warning sign for future earnings."
                )

        category_scores["Revenue Growth"] = revenue_score
        overall_score += revenue_score

        # ----------------------------
        # Profitability
        # ----------------------------

        margin_score = 5
        margin = stock.get("profit_margin")

        if margin is not None:

            if margin >= 0.25:
                margin_score = 10
                strengths.append("Excellent profitability.")
                reasoning["Profitability"] = (
                    f"Profit margin of {margin:.1%} is outstanding and "
                    "indicates excellent operational efficiency."
                )

            elif margin >= 0.15:
                margin_score = 8
                strengths.append("Strong profitability.")
                reasoning["Profitability"] = (
                    f"Profit margin of {margin:.1%} is above average."
                )

            elif margin >= 0.05:
                margin_score = 6
                reasoning["Profitability"] = (
                    "Profitability is acceptable but has room for improvement."
                )

            else:
                margin_score = 2
                weaknesses.append("Weak profitability.")
                reasoning["Profitability"] = (
                    "Low margins may reduce future earnings potential."
                )

        category_scores["Profitability"] = margin_score
        overall_score += margin_score

        # ----------------------------
        # Return on Equity
        # ----------------------------

        roe_score = 5
        roe = stock.get("return_on_equity")

        if roe is not None:

            if roe >= 0.25:
                roe_score = 10
                strengths.append("Excellent return on equity.")
                reasoning["Capital Efficiency"] = (
                    f"ROE of {roe:.1%} demonstrates management is generating "
                    "strong returns on shareholder capital."
                )

            elif roe >= 0.15:
                roe_score = 8
                strengths.append("Healthy return on equity.")
                reasoning["Capital Efficiency"] = (
                    f"ROE of {roe:.1%} is above average."
                )

            elif roe >= 0.08:
                roe_score = 6
                reasoning["Capital Efficiency"] = (
                    "Return on equity is acceptable."
                )

            else:
                roe_score = 2
                weaknesses.append("Low return on equity.")
                reasoning["Capital Efficiency"] = (
                    "Management is producing relatively weak returns on capital."
                )

        category_scores["Capital Efficiency"] = roe_score
        overall_score += roe_score

        # ----------------------------
        # Debt
        # ----------------------------

        debt_score = 5
        debt = stock.get("debt_to_equity")

        if debt is not None:

            if debt < 50:
                debt_score = 10
                strengths.append("Very conservative debt levels.")
                reasoning["Financial Health"] = (
                    "Debt levels are very manageable."
                )

            elif debt < 100:
                debt_score = 8
                strengths.append("Healthy balance sheet.")
                reasoning["Financial Health"] = (
                    "Debt appears well controlled."
                )

            elif debt < 200:
                debt_score = 6
                reasoning["Financial Health"] = (
                    "Debt is acceptable but worth monitoring."
                )

            else:
                debt_score = 2
                weaknesses.append("High debt levels.")
                reasoning["Financial Health"] = (
                    "Debt is elevated and may increase financial risk."
                )

        category_scores["Financial Health"] = debt_score
        overall_score += debt_score

        # ----------------------------
        # Free Cash Flow
        # ----------------------------

        cash_score = 5
        cash = stock.get("free_cashflow")

        if cash is not None:

            if cash > 0:
                cash_score = 10
                strengths.append("Positive free cash flow.")
                reasoning["Cash Flow"] = (
                    "Positive free cash flow gives the company flexibility "
                    "to invest, reduce debt, or return capital to shareholders."
                )

            else:
                cash_score = 2
                weaknesses.append("Negative free cash flow.")
                reasoning["Cash Flow"] = (
                    "Negative free cash flow may reduce financial flexibility."
                )

        category_scores["Cash Flow"] = cash_score
        overall_score += cash_score

        # Convert 50-point scale to 100-point scale

        overall_score *= 2

        return AnalysisResult(

            analyzer_name="Financial Analysis",

            overall_score=overall_score,

            category_scores=category_scores,

            strengths=strengths,

            weaknesses=weaknesses,

            reasoning=reasoning,

            metrics={
                "Revenue Growth": revenue_growth,
                "Profit Margin": margin,
                "Return On Equity": roe,
                "Debt To Equity": debt,
                "Free Cash Flow": cash,
            },
        )