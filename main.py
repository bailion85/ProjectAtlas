from core.services.openai_service import OpenAIService


def main():

    print("=" * 60)
    print("🚀 Project Atlas")
    print("=" * 60)

    print("Version: 0.0.1")
    print("Status: Online")
    print()

    service = OpenAIService()

    print("Atlas is thinking...")
    print()

    response = service.ask(
        "Introduce yourself as Atlas. You are an AI investment analyst that will help manage a $1,000 investment portfolio. Keep your introduction to about 150 words."
    )

    print(response)


if __name__ == "__main__":
    main()