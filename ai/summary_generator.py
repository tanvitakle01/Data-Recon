class SummaryGenerator:

    def generate(self, stats):

        return f"""
Missing in Target : {stats['missing_count']}
Extra in Target   : {stats['extra_count']}
Qty Mismatch      : {stats['qty_mismatch_count']}
Total Mismatches  : {stats['total_mismatches']}
"""