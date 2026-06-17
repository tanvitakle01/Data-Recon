import pandas as pd


class InsightEngine:

    def generate(self, df):

        insights = []

        if df.empty:
            return insights

        remarks = df["Remarks"].fillna("").astype(str)

        mismatch_df = df[
            remarks.str.contains(
                "MISSING IN TARGET|EXTRA IN TARGET|QTY MISMATCH",
                case=False,
                regex=True
            )
        ]

        if mismatch_df.empty:
            return insights

        # --------------------------------------------------
        # Location Analysis
        # --------------------------------------------------

        if mismatch_df.columns[0] is not None:

            location_col = mismatch_df.columns[0]

            top_locations = (
                mismatch_df[location_col]
                .value_counts()
                .head(5)
            )

            insights.append(
                f"Top mismatch locations: {', '.join(top_locations.index.astype(str))}"
            )

        # --------------------------------------------------
        # Product Analysis
        # --------------------------------------------------

        if len(mismatch_df.columns) > 1:

            product_col = mismatch_df.columns[1]

            top_products = (
                mismatch_df[product_col]
                .value_counts()
                .head(5)
            )

            insights.append(
                f"Top mismatch products: {', '.join(top_products.index.astype(str))}"
            )

        # --------------------------------------------------
        # Mismatch Type Analysis
        # --------------------------------------------------

        missing_count = remarks.str.contains(
            "MISSING IN TARGET",
            case=False
        ).sum()

        extra_count = remarks.str.contains(
            "EXTRA IN TARGET",
            case=False
        ).sum()

        qty_count = remarks.str.contains(
            "QTY MISMATCH",
            case=False
        ).sum()

        if missing_count > extra_count and missing_count > qty_count:
            insights.append(
                "Missing records are the dominant mismatch category."
            )

        elif extra_count > missing_count and extra_count > qty_count:
            insights.append(
                "Extra records are the dominant mismatch category."
            )

        elif qty_count > 0:
            insights.append(
                "Quantity differences contribute significantly to mismatches."
            )

        return insights