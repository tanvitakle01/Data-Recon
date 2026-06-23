from backend.API_conn.connectors.s4_connector import S4SalesOrderConnector


def main():
    print("=" * 60)
    print("TESTING S4 CONNECTOR")
    print("=" * 60)

    try:
        connector = S4SalesOrderConnector()

        print("✅ Connector initialized")
        print()

        df = connector.fetch()

        print("✅ Fetch executed")
        print(f"Type: {type(df)}")
        print(f"Shape: {df.shape}")

        if df.empty:
            print("⚠️ DataFrame is empty")
        else:
            print("\nColumns:")
            print(df.columns.tolist())

            print("\nPreview:")
            print(df.head())

    except Exception as e:
        print(f"❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()