from pprint import pprint

from backend.API_conn.config.config_loader import load_config


def main():
    print("=" * 80)
    print("CONFIG DIAGNOSTIC")
    print("=" * 80)

    config = load_config()

    print("\nALL CONFIG:")
    pprint(config)

    print("\nS4 CONFIG:")
    pprint(config.get("s4"))

    print("\nIBP CONFIG:")
    pprint(config.get("ibp"))


if __name__ == "__main__":
    main()