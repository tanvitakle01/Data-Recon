"""Fact-based reconciliation insights — one pipeline shared by all three
entry points (the post-run "View Insights" button, the Insights tab's
workbook upload, and the chat assistant's PDF), always built on top of the
same results-excel schema (`service.build_comparison_workbook`'s Summary /
All Records / Mapping Details sheets).

See `normalize.py` (converts a run or an uploaded workbook into one common
shape), `facts.py` (pure counts/rankings/distributions — no adjectives, no
scores), `query.py` (drill-through record filtering), `pdf.py` (structured
PDF export), and `builder.py` (the entry points routes actually call).
"""
