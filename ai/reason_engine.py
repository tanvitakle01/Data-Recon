class ReasonEngine:

    def generate(self, stats):

        reasons = []

        if stats["missing_count"] > 0:
            reasons.append(
                "Records exist in Source but are not present in Target."
            )

        if stats["extra_count"] > 0:
            reasons.append(
                "Records exist in Target but are not present in Source."
            )

        if stats["qty_mismatch_count"] > 0:
            reasons.append(
                "Matching records were found but quantity values differ."
            )

        if stats["total_mismatches"] > 100:
            reasons.append(
                "Large mismatch volume detected. Verify extraction date, filters, and master data alignment."
            )

        return reasons