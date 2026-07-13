from __future__ import annotations

# Static for now — a future iteration can move this to a DB table so new
# comparison types don't require a deploy (see architecture note on
# "comparison types as data").
COMPARISON_TYPES = [
    {
        "id": "sales_history",
        "label": "Sales History",
        "domain": "Sales",
        "description": "Actual sales transactions between two systems of record.",
    },
    {
        "id": "sales_orders",
        "label": "Sales Orders",
        "domain": "Sales",
        "description": "Open and fulfilled sales order line items.",
    },
    {
        "id": "demand_plan",
        "label": "Demand Plan",
        "domain": "Planning",
        "description": "Statistical or consensus demand plan quantities by period.",
    },
    {
        "id": "forecast",
        "label": "Forecast",
        "domain": "Planning",
        "description": "Forecasted demand or supply figures by period.",
    },
    {
        "id": "inventory",
        "label": "Inventory",
        "domain": "Supply Chain",
        "description": "On-hand, in-transit, or projected inventory balances.",
    },
    {
        "id": "purchase_orders",
        "label": "Purchase Orders",
        "domain": "Procurement",
        "description": "Open and fulfilled purchase order line items.",
    },
    {
        "id": "material_master",
        "label": "Material Master",
        "domain": "Master Data",
        "description": "Material or product master attributes.",
    },
    {
        "id": "customer_master",
        "label": "Customer Master",
        "domain": "Master Data",
        "description": "Customer master attributes.",
    },
    {
        "id": "financial_balances",
        "label": "Financial Balances",
        "domain": "Finance",
        "description": "General ledger or sub-ledger account balances.",
    },
    {
        "id": "custom",
        "label": "Custom Dataset",
        "domain": "Custom",
        "description": "Any other dataset pair not covered above.",
    },
]


def list_comparison_types() -> list[dict]:
    return COMPARISON_TYPES


def get_comparison_type(comparison_type_id: str) -> dict | None:
    return next((c for c in COMPARISON_TYPES if c["id"] == comparison_type_id), None)
