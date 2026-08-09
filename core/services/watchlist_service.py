import json


class WatchlistService:

    def __init__(self):
        with open("data/watchlist.json", "r") as file:
            self.watchlist = json.load(file)["watchlist"]

    def get_watchlist(self):
        return self.watchlist