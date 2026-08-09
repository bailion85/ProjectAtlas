class Formatter:

    @staticmethod
    def format_currency(value):

        if value is None:
            return "N/A"

        if value >= 1_000_000_000_000:
            return f"${value/1_000_000_000_000:.2f}T"

        if value >= 1_000_000_000:
            return f"${value/1_000_000_000:.2f}B"

        if value >= 1_000_000:
            return f"${value/1_000_000:.2f}M"

        return f"${value:,.2f}"