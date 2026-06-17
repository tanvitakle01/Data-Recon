class ReasonEngine:

    def generate(self, stats):

        reasons = []

        if stats.get("missing_count", 0) > 0:
            reasons.append(
                "Records exist in Source but are not present in Target."
            )

        if stats.get("extra_count", 0) > 0:
            reasons.append(
                "Records exist in Target but are not present in Source."
            )

        if stats.get("qty_mismatch_count", 0) > 0:
            reasons.append(
                "Matching records contain quantity differences."
            )

        if stats.get("total_mismatches", 0) > 100:
            reasons.append(
                "Large mismatch volume detected. Verify extraction date, filters, and master data alignment."
            )

        return reasons