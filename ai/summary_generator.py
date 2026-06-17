class SummaryGenerator:

    def generate(self, stats):

        return f"""
Missing in Target : {stats.get('missing_count', 0)}
Extra in Target : {stats.get('extra_count', 0)}
Qty Mismatch : {stats.get('qty_mismatch_count', 0)}
Total Mismatches : {stats.get('total_mismatches', 0)}
"""