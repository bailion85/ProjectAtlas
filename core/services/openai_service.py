from pathlib import Path
from dotenv import load_dotenv
import os
from openai import OpenAI


class OpenAIService:

    def __init__(self):
        # Find the .env file in the ProjectAtlas folder
        env_path = Path(__file__).resolve().parents[2] / ".env"
        load_dotenv(env_path)

        # Read the API key
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in .env")

        # Create the OpenAI client
        self.client = OpenAI(api_key=api_key)

    def ask(self, prompt):
        response = self.client.responses.create(
            model="gpt-5.5",
            input=prompt
        )

        return response.output_text


if __name__ == "__main__":
    print("Starting OpenAIService test...")

    service = OpenAIService()

    print("✅ Success! OpenAIService loaded correctly.")