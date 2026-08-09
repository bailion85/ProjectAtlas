"""
Project Atlas
Main Entry Point
"""

from core.config.settings import APP_NAME, VERSION


def main():
    print("=" * 60)
    print(f"🚀 {APP_NAME}")
    print("=" * 60)
    print(f"Version: {VERSION}")
    print("Status: Online")
    print("=" * 60)


if __name__ == "__main__":
    main()

