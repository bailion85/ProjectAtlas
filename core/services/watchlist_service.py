import json
from pathlib import Path


class WatchlistService:

    def __init__(self):
        self.file_path = Path("data/watchlist.json")

        if not self.file_path.exists():
            self.watchlist = {
                "watchlist": [
                     "AAPL",
                    "MSFT",
                    "GOOGL",
                    "AMZN",
                    "META",
                    "TSLA",
                    "SPCX",
                    "IONQ",
                    "WMT",
                    "FTEC",
                    "DDM",
                    "VYM",
                    "SPYM",
                    "RKLB",
                    "ANET",
                    "PLTR",
                    "CRDO",
                    "TSM",
                    "CCJ",
                    "SNOW",
                    "AMD",
                    "RBRK",
                    "SCHD",
                    "NVDA",
                    "RTX",
                    "V",
                    "COST"
                ]
            }

            self.save()

        else:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.watchlist = json.load(file)

    def get_watchlist(self):
        return self.watchlist["watchlist"]

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(self.watchlist, file, indent=4)