class ScoringService:

    def score_stock(self, stock):

        score = 50

        # Valuation
        pe = stock.get("pe_ratio")

        if pe is not None:

            if pe < 20:
                score += 15

            elif pe < 30:
                score += 10

            elif pe > 40:
                score -= 10

        # Analyst Recommendation
        recommendation = stock.get("recommendation")

        if recommendation == "buy":
            score += 15

        elif recommendation == "strong_buy":
            score += 20

        elif recommendation == "sell":
            score -= 20

        # Dividend
        dividend = stock.get("dividend_yield")

        if dividend:
            score += 5

        return max(0, min(score, 100))