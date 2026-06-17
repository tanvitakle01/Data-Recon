class RootCauseEngine:

    def identify(self, stats):

        causes = []

        if stats.get("missing_count", 0) > 0:
            causes.append(
                "Target load may be incomplete or source records were filtered out."
            )

        if stats.get("extra_count", 0) > 0:
            causes.append(
                "Target may contain historical, duplicate, or obsolete records."
            )

        if stats.get("qty_mismatch_count", 0) > 0:
            causes.append(
                "Transformation, aggregation, or unit conversion issues may exist."
            )

        if stats.get("total_mismatches", 0) > 1000:
            causes.append(
                "Possible full-load, extraction-date, or master-data alignment issue."
            )

        return causes