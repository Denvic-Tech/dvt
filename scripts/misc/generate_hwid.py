from src.security.hwid import generate_hwid  # noqa: F821


def main():
    try:
        hwid = generate_hwid()
        print(f"Generated HWID: {hwid}")
        print(f"HWID length: {len(hwid)} characters")
    except Exception as e:
        print(f"Error occurred while generating HWID: {e}")

if __name__ == "__main__":
    main()
