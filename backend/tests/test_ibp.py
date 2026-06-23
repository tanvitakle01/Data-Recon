from backend.API_conn.connectors.ibp_connector import IBPDemandConnector
import pandas as pd


def main():
    print("=" * 60)
    print("TESTING IBP CONNECTOR")
    print("=" * 60)

    try:
        connector = IBPDemandConnector()
        print("✅ Connector initialized")
    except Exception as e:
        print(f"❌ Connector initialization failed: {e}")
        return

    try:
        df = connector.fetch()

        print("\n✅ Fetch executed")
        print(f"Type: {type(df)}")

        if not isinstance(df, pd.DataFrame):
            print("❌ Fetch did not return a DataFrame")
            return

        print(f"Shape: {df.shape}")

        if df.empty:
            print("⚠️ DataFrame is empty")
        else:
            print("\nColumns:")
            print(df.columns.tolist())

            print("\nFirst 5 rows:")
            print(df.head())

            print(f"\nTotal Rows: {len(df)}")
            print(f"Total Columns: {len(df.columns)}")

    except Exception as e:
        print(f"\n❌ Fetch failed")
        print(type(e).__name__)
        print(str(e))


if __name__ == "__main__":
    main()