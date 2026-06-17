# Excel Source vs Target Comparator (Phase 1)

A Streamlit application for comparing Source and Target (IBP) Excel files with runtime column mapping.

## Features

- Upload Source and Target Excel files (`.xlsx` and `.xls`)
- Multi-sheet selection support
- Runtime mapping for key and compare fields (no hardcoded column names)
- Scenario-based comparison engine:
  - Scenario 1: Matching Combinations
  - Scenario 2: Quantity Mismatch on matched keys
  - Scenario 3: Missing in Target (append rows)
  - Bonus: Extra in Target
- Annotated output Excel with color-coded `Remarks`
- Summary metrics, scenario filter, and chart in UI

## Project Structure

```text
excel_comparator/
├── app.py
├── core/
│   ├── __init__.py
│   ├── loader.py
│   ├── mapper.py
│   ├── comparator.py
│   └── writer.py
├── utils/
│   ├── __init__.py
│   └── helpers.py
├── requirements.txt
└── README.md
```

## Run Locally

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
streamlit run app.py
```

## Notes

- Output is always generated as `.xlsx`.
- Target schema is preserved, with `Remarks` appended as last column.
- If `Remarks` already exists in target, it is replaced to avoid duplicates.
- Default key matching options are case-insensitive and whitespace-trimmed.
