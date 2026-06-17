class MismatchAnalyzer:

    def analyze(self, summary):

        return {
            "missing_count": summary.get("missing_in_target", 0),
            "extra_count": summary.get("extra_in_target", 0),
            "qty_mismatch_count": summary.get("qty_mismatch", 0),
            "matched_count": summary.get("matched", 0),
            "total_mismatches":
                summary.get("missing_in_target", 0)
                + summary.get("extra_in_target", 0)
                + summary.get("qty_mismatch", 0)
        }