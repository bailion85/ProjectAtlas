class StockAnalysis:

    def __init__(self, stock, score):

        self.symbol = stock["symbol"]
        self.company = stock["name"]
        self.price = stock["price"]
        self.score = score
        self.sector = stock["sector"]

    def __repr__(self):
        return f"{self.symbol} ({self.score})"