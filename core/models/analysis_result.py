class AnalysisResult:
    """
    Standard result returned from any Atlas analyzer.
    """

    def __init__(
        self,
        analyzer_name,
        overall_score,
        category_scores=None,
        strengths=None,
        weaknesses=None,
        reasoning=None,
        metrics=None,
    ):

        self.analyzer_name = analyzer_name
        self.overall_score = overall_score
        self.category_scores = category_scores or {}
        self.strengths = strengths or []
        self.weaknesses = weaknesses or []
        self.reasoning = reasoning or {}
        self.metrics = metrics or {}

    def __str__(self):

        output = []

        output.append("=" * 60)
        output.append(self.analyzer_name)
        output.append("=" * 60)
        output.append(f"Overall Score: {self.overall_score}/100")
        output.append("")

        if self.category_scores:
            output.append("CATEGORY SCORES")
            output.append("-" * 60)

            for category, score in self.category_scores.items():
                output.append(f"{category:<25}{score}/10")

            output.append("")

        if self.strengths:
            output.append("STRENGTHS")
            output.append("-" * 60)

            for strength in self.strengths:
                output.append(f"✓ {strength}")

            output.append("")

        if self.weaknesses:
            output.append("WEAKNESSES")
            output.append("-" * 60)

            for weakness in self.weaknesses:
                output.append(f"• {weakness}")

            output.append("")

        if self.reasoning:
            output.append("REASONING")
            output.append("-" * 60)

            for section, text in self.reasoning.items():
                output.append(f"{section}:")
                output.append(text)
                output.append("")

        if self.metrics:
            output.append("METRICS")
            output.append("-" * 60)

            for metric, value in self.metrics.items():
                output.append(f"{metric:<30}{value}")

        return "\n".join(output)