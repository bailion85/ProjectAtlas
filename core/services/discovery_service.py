import json
from pathlib import Path


class DiscoveryService:
    """
    Responsible for providing stocks that are NOT currently
    on the user's watchlist.
    """

    def __init__(self):

        # Project Root
        self.project_root = Path(__file__).resolve().parents[2]

        # data/discovery_universe.json
        self.file_path = self.project_root / "data" / "discovery_universe.json"

    def get_universe(self):

        #
        # Verify file exists
        #

        if not self.file_path.exists():

            print(f"Discovery universe not found:\n{self.file_path}")

            return []

        #
        # Read file
        #

        with open(self.file_path, "r", encoding="utf-8") as file:

            contents = file.read().strip()

        #
        # Empty file?
        #

        if not contents:

            print("Discovery universe is empty.")

            return []

        #
        # Parse JSON
        #

        try:

            return json.loads(contents)

        except json.JSONDecodeError as error:

            print("Invalid JSON in discovery_universe.json")

            print(error)

            return []

    def get_candidates(self, watchlist):

        universe = self.get_universe()

        #
        # Remove watchlist companies
        #

        candidates = []

        for ticker in universe:

            if ticker not in watchlist:

                candidates.append(ticker)

        return candidates

    def get_candidate_count(self, watchlist):

        return len(self.get_candidates(watchlist))