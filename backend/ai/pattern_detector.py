class PatternDetector:

    def detect(self, stats):

        patterns = []

        total = stats.get("total_mismatches", 0)

        if total == 0:
            patterns.append("No mismatch patterns detected.")
            return patterns

        missing = stats.get("missing_count", 0)
        extra = stats.get("extra_count", 0)
        qty = stats.get("qty_mismatch_count", 0)

        if missing > extra and missing > qty:
            patterns.append(
                "Missing records are the dominant mismatch category."
            )

        if extra > missing and extra > qty:
            patterns.append(
                "Extra target records are the dominant mismatch category."
            )

        if qty > missing and qty > extra:
            patterns.append(
                "Quantity differences are the dominant mismatch category."
            )

        if total > 1000:
            patterns.append(
                "High-volume reconciliation failure detected."
            )

        return patterns