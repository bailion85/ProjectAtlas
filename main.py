from atlas import Atlas


def main():

    atlas = Atlas()

    while True:

        print("\n" + "=" * 70)
        print("PROJECT ATLAS")
        print("=" * 70)

        print("1. Analyze My Watchlist")
        print("2. Discover New Opportunities")
        print("3. Exit")

        choice = input("\nSelect an option: ")

        if choice == "1":

            atlas.run_watchlist()

        elif choice == "2":

            atlas.run_discovery()

        elif choice == "3":

            print("\nGoodbye.")
            break

        else:

            print("\nInvalid selection.")


if __name__ == "__main__":
    main()