class Recommendation:

    def __init__(
        self,
        ticker,
        score,
        summary,
        strengths,
        risks
    ):
        self.ticker = ticker
        self.score = score
        self.summary = summary
        self.strengths = strengths
        self.risks = risks