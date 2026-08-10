class CompanyAnalysis:

    def __init__(
        self,
        ticker,
        company,
        stock,
        financial_analysis
    ):

        self.ticker = ticker
        self.company = company

        self.stock = stock

        self.financial = financial_analysis

    @property
    def score(self):

        return self.financial.overall_score