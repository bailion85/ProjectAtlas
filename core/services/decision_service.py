class DecisionService:

    def rank(self, analyses):

        return sorted(
            analyses,
            key=lambda analysis: analysis.score,
            reverse=True
        )

    def recommend(self, analyses):

        ranked = self.rank(analyses)

        return ranked[0]