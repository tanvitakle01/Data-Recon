"""Sequential AI mapping resolution: gating discipline + chained wiring.

The LLM is faked so these tests are deterministic. The point isn't the model
but the wrapper's contract at every step: only real column names / allow-listed
operations survive, invented or out-of-range values are dropped, and any step
failure degrades gracefully rather than raising or poisoning later steps.
"""

from __future__ import annotations

import pytest

from backend.recon_engine import mapping_resolution as mr


class _FakeClient:
    def __init__(self, payload=None, raises=None):
        self._payload = payload
        self._raises = raises

    def complete_json(self, messages):  # noqa: ARG002 - signature match
        if self._raises is not None:
            raise self._raises
        return self._payload


class _SequencedClient:
    """Returns a different fake client's payload per call, in order."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0

    def complete_json(self, messages):  # noqa: ARG002
        payload = self._payloads[self.calls]
        self.calls += 1
        return payload


class _RecordingClient:
    """Records the user-message payload of every call it receives, so a test
    can assert exactly what was (or wasn't) sent to the LLM."""

    def __init__(self, payload):
        self._payload = payload
        self.sent_payloads: list[dict] = []

    def complete_json(self, messages):
        import json as _json

        self.sent_payloads.append(_json.loads(messages[-1]["content"]))
        return self._payload


@pytest.fixture
def llm_configured(monkeypatch):
    monkeypatch.setattr(mr, "get_settings", lambda: type("S", (), {"any_llm_configured": True})())


def _install(monkeypatch, client):
    monkeypatch.setattr(mr, "build_llm_client", lambda: client)


_MAPPING_SHEET = {
    "headers": ["Source Table/Field", "Business Field", "Target Field", "Transformation", "Filter"],
    "rows": [
        {"Source Table/Field": "VBAP-MATNR", "Business Field": "Material", "Target Field": "PRDID",
         "Transformation": "Prepend 'PL'", "Filter": None},
        {"Source Table/Field": "VBAP-WERKS", "Business Field": "Plant", "Target Field": "LOCID",
         "Transformation": None, "Filter": "Sales Org = 5875"},
        {"Source Table/Field": "VBAP-UNUSED", "Business Field": "Unused Field", "Target Field": "ZZZ",
         "Transformation": None, "Filter": None},
    ],
    "mapping_candidates": [
        {"row_index": 0, "source_field": "Material", "target_field": "PRDID",
         "technical_field": "VBAP-MATNR", "description": None,
         "transformation": "Prepend 'PL'", "join_condition": None, "filter": None},
        {"row_index": 1, "source_field": "Plant", "target_field": "LOCID",
         "technical_field": "VBAP-WERKS", "description": None,
         "transformation": None, "join_condition": None, "filter": "Sales Org = 5875"},
        {"row_index": 2, "source_field": "Unused Field", "target_field": "ZZZ",
         "technical_field": "VBAP-UNUSED", "description": None,
         "transformation": None, "join_condition": None, "filter": None},
    ],
}

_SOURCE_COLUMNS = ["Material", "Plant", "SalesOrg", "OrderQty"]
_TARGET_COLUMNS = ["PRDID", "LOCID", "SALESORDERREQUEST"]


# ── step 1 ───────────────────────────────────────────────────────────────────

def test_select_relevant_fields_gates_out_of_range_indices(monkeypatch, llm_configured):
    _install(monkeypatch, _FakeClient(payload={"relevant_row_indices": [0, 1, 99, "not-an-int"]}))
    result = mr.select_relevant_fields(_MAPPING_SHEET, _SOURCE_COLUMNS, _TARGET_COLUMNS)

    assert result["degraded_reason"] is None
    indices = [c["row_index"] for c in result["relevant_candidates"]]
    assert indices == [0, 1]  # row 2 (unused) and the invented indices are dropped
    assert len(result["relevant_rows"]) == 2


def test_select_relevant_fields_degrades_on_llm_failure(monkeypatch, llm_configured):
    _install(monkeypatch, _FakeClient(raises=RuntimeError("boom")))
    result = mr.select_relevant_fields(_MAPPING_SHEET, _SOURCE_COLUMNS, _TARGET_COLUMNS)

    assert result["degraded_reason"] is not None
    assert result["relevant_candidates"] == []


# ── step 2 ───────────────────────────────────────────────────────────────────

def test_enrich_relevant_fields_resolves_and_drops_invented_columns(monkeypatch, llm_configured):
    candidates = _MAPPING_SHEET["mapping_candidates"][:2]
    rows = _MAPPING_SHEET["rows"][:2]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "enriched_fields": [
                    {"row_index": 0, "source_column": "material", "source_table": "VBAP",
                     "datatype": None, "description": "Material number"},
                    {"row_index": 1, "source_column": "NoSuchColumn", "source_table": "VBAP",
                     "datatype": None, "description": "Plant"},
                ]
            }
        ),
    )
    result = mr.enrich_relevant_fields(candidates, rows, _SOURCE_COLUMNS)

    assert len(result["enriched_fields"]) == 1
    assert result["enriched_fields"][0]["source_column"] == "Material"  # case-resolved to real column
    assert result["enriched_fields"][0]["source_table"] == "VBAP"


# ── step 4 ───────────────────────────────────────────────────────────────────

def test_compile_deterministic_operations_gates_registry_and_params(monkeypatch, llm_configured):
    chain = [{"step": 1, "intent": "transform", "description": "Prepend PL to Material", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": "Material number"}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [
                    {"op": "prepend_prefix", "field": "Material", "params": {"value": "PL"}},
                    {"op": "not_a_real_op", "field": "Material", "params": {}},
                    {"op": "prepend_prefix", "field": "NotAColumn", "params": {"value": "PL"}},
                    {"op": "prepend_prefix", "field": "Material", "params": {}},  # missing required param
                ]
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert len(result["operations"]) == 1
    op = result["operations"][0]
    assert op == {"op": "prepend_prefix", "field": "Material", "params": {"value": "PL"}, "enabled": True}
    assert result["proposed_operations"] == []


def test_compile_deterministic_operations_recovers_field_nested_inside_params(monkeypatch, llm_configured):
    # The model sometimes nests "field" inside "params" instead of emitting
    # it at the top level — this must not be treated as an invalid operation
    # (it previously failed BOTH "requires a field" and "unexpected param
    # 'field'" simultaneously, guaranteeing it was dropped).
    chain = [{"step": 1, "intent": "filter", "description": "Exclude Sales Org 9999", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "SalesOrg", "source_table": None,
                 "datatype": None, "description": None}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [
                    {
                        "op": "exclude_value",
                        "field": None,
                        "params": {"field": "SalesOrg", "values": ["9999"]},
                    }
                ]
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["operations"] == [
        {"op": "exclude_value", "field": "SalesOrg", "params": {"values": ["9999"]}, "enabled": True}
    ]


def test_compile_deterministic_operations_drops_hallucinated_compare_to_and_bad_enum(monkeypatch, llm_configured):
    # A hallucinated `compare_to` column, and an invalid `date_condition`
    # value, are both caught by OperationSpec.validate() before an operation
    # ever reaches `operations` — never left to fail only at Gate 2 replay.
    chain = [{"step": 1, "intent": "transform", "description": "Roll a past-due date forward", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": None}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [
                    {
                        "op": "relative_date_reassign",
                        "field": "Material",
                        "params": {"date_condition": "lt", "offset_days": 1, "compare_to": "InventedColumn"},
                    },
                    {
                        "op": "relative_date_reassign",
                        "field": "Material",
                        "params": {"date_condition": "before", "offset_days": 1},
                    },
                ]
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["operations"] == []


# ── date_bucket -> aggregate_group bonded-unit enforcement ──────────────────

def test_bond_date_bucket_inserts_missing_bucketed_field_into_group_by():
    candidates = [
        {"op": "date_bucket", "field": "OrderDate", "params": {"granularity": "month"}},
        {
            "op": "aggregate_group",
            "field": None,
            "params": {"by": ["Material", "Plant"], "aggregations": [{"field": "OrderQty", "func": "sum"}]},
        },
    ]
    mr._bond_date_bucket_to_aggregate_group(candidates)

    assert candidates[1]["params"]["by"] == ["Material", "Plant", "OrderDate"]


def test_bond_date_bucket_is_noop_when_already_wired():
    candidates = [
        {"op": "date_bucket", "field": "OrderDate", "params": {"granularity": "month"}},
        {
            "op": "aggregate_group",
            "field": None,
            "params": {"by": ["Material", "OrderDate"], "aggregations": [{"field": "OrderQty", "func": "sum"}]},
        },
    ]
    mr._bond_date_bucket_to_aggregate_group(candidates)

    assert candidates[1]["params"]["by"] == ["Material", "OrderDate"]  # unchanged, not duplicated


def test_bond_date_bucket_wires_even_when_not_adjacent():
    # A transform in between no longer blocks the bond — the executor's fixed
    # pipeline runs all TRANSFORMs (date_bucket included) before any
    # AGGREGATE, so position in the chain doesn't affect what actually runs.
    candidates = [
        {"op": "date_bucket", "field": "OrderDate", "params": {"granularity": "month"}},
        {"op": "trim_string", "field": "Material", "params": {}},
        {"op": "aggregate_group", "field": None, "params": {"by": ["Material"], "aggregations": []}},
    ]
    mr._bond_date_bucket_to_aggregate_group(candidates)
    assert candidates[2]["params"]["by"] == ["Material", "OrderDate"]

    # date_bucket itself unresolved (field=None, would be dropped anyway) -> nothing to wire.
    unresolved = [
        {"op": "date_bucket", "field": None, "params": {"granularity": "month"}},
        {"op": "aggregate_group", "field": None, "params": {"by": ["Material"], "aggregations": []}},
    ]
    mr._bond_date_bucket_to_aggregate_group(unresolved)
    assert unresolved[1]["params"]["by"] == ["Material"]


def test_bond_date_bucket_wires_when_aggregate_group_comes_first():
    # Reversed order (the model emitted the aggregate before the bucket) ->
    # still wired, since the bond searches the whole candidate list.
    candidates = [
        {"op": "aggregate_group", "field": None, "params": {"by": ["Material"], "aggregations": []}},
        {"op": "date_bucket", "field": "OrderDate", "params": {"granularity": "month"}},
    ]
    mr._bond_date_bucket_to_aggregate_group(candidates)
    assert candidates[0]["params"]["by"] == ["Material", "OrderDate"]


def test_compile_deterministic_operations_auto_wires_date_bucket_into_aggregate_group(monkeypatch, llm_configured):
    chain = [
        {"step": 1, "intent": "date_rebucket", "description": "Bucket OrderDate to month", "row_indices": [0]},
        {"step": 2, "intent": "aggregate", "description": "Sum OrderQty by Material/Plant/month", "row_indices": [0, 1]},
    ]
    enriched = [
        {"row_index": 0, "source_column": "OrderDate", "source_table": None, "datatype": None, "description": None},
        {"row_index": 1, "source_column": "Material", "source_table": None, "datatype": None, "description": None},
    ]
    source_columns = ["OrderDate", "Material", "Plant", "OrderQty"]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [
                    {"op": "date_bucket", "field": "OrderDate", "params": {"granularity": "month"}},
                    {
                        "op": "aggregate_group",
                        "field": None,
                        # The model forgot to include the bucketed date dimension in `by`.
                        "params": {"by": ["Material", "Plant"], "aggregations": [{"field": "OrderQty", "func": "sum"}]},
                    },
                ]
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, source_columns)

    assert len(result["operations"]) == 2
    agg_op = result["operations"][1]
    assert agg_op["op"] == "aggregate_group"
    assert agg_op["params"]["by"] == ["Material", "Plant", "OrderDate"]


def test_compile_deterministic_operations_rejects_measure_that_is_also_group_by_key(monkeypatch, llm_configured):
    chain = [{"step": 1, "intent": "aggregate", "description": "Bad node", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "Material", "source_table": None, "datatype": None, "description": None}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [
                    {
                        "op": "aggregate_group",
                        "field": None,
                        "params": {"by": ["Material"], "aggregations": [{"field": "Material", "func": "count"}]},
                    }
                ]
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["operations"] == []  # rejected: Material is both the group-by key and the measure


def test_compile_deterministic_operations_surfaces_genuine_new_proposal(monkeypatch, llm_configured):
    chain = [{"step": 1, "intent": "transform", "description": "Some unsupported shape", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": "Material number"}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [],
                "proposed_operations": [
                    {
                        "name": "fiscal_period_bucket",
                        "kind": "transform",
                        "params": {"field": "column", "fiscal_year_start_month": "int 1-12"},
                        "contract": "Buckets a date into the company's fiscal period, which starts "
                        "in a configurable month — no existing operation models a non-calendar "
                        "fiscal year.",
                    }
                ],
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["operations"] == []
    assert len(result["proposed_operations"]) == 1
    assert result["proposed_operations"][0]["name"] == "fiscal_period_bucket"


def test_compile_deterministic_operations_drops_proposal_naming_an_existing_op(monkeypatch, llm_configured):
    chain = [{"step": 1, "intent": "transform", "description": "Prepend PL", "row_indices": [0]}]
    enriched = [{"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": None}]
    _install(
        monkeypatch,
        _FakeClient(
            payload={
                "operations": [],
                "proposed_operations": [
                    {"name": "prepend_prefix", "kind": "transform", "params": {}, "contract": "Should have been used directly."}
                ],
            }
        ),
    )
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["proposed_operations"] == []  # already-real ops are never "proposals"


# ── value_crosswalk gating ───────────────────────────────────────────────────

def test_compile_deterministic_operations_flags_crosswalk_without_llm_call(monkeypatch, llm_configured):
    # A chain of ONLY value_crosswalk nodes must never reach the LLM at all —
    # there is nothing here for it to compile, and this must be a
    # deterministic gate, not a prompt instruction the model could ignore.
    chain = [
        {"step": 1, "intent": "value_crosswalk", "description": "Map plant codes via the code table",
         "row_indices": [0]},
    ]
    enriched = [{"row_index": 0, "source_column": "Plant", "source_table": "VBAP",
                 "datatype": None, "description": None}]

    def _boom(*_a, **_k):
        raise AssertionError("LLM must never be called for a crosswalk-only chain")

    monkeypatch.setattr(mr, "build_llm_client", _boom)
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert result["operations"] == []
    assert result["proposed_operations"] == []
    assert result["requires_value_pairing"] == [
        {"source_column": "Plant", "description": "Map plant codes via the code table", "row_index": 0}
    ]
    assert result["degraded"] is False


def test_compile_deterministic_operations_excludes_crosswalk_nodes_from_llm_payload(monkeypatch, llm_configured):
    # A MIXED chain still calls the LLM for the non-crosswalk node, but the
    # crosswalk node itself is never included in what's sent.
    chain = [
        {"step": 1, "intent": "transform", "description": "Prepend PL to Material", "row_indices": [0]},
        {"step": 2, "intent": "value_crosswalk", "description": "Map plant codes via the code table",
         "row_indices": [1]},
    ]
    enriched = [
        {"row_index": 0, "source_column": "Material", "source_table": "VBAP", "datatype": None, "description": None},
        {"row_index": 1, "source_column": "Plant", "source_table": "VBAP", "datatype": None, "description": None},
    ]
    client = _RecordingClient(
        payload={"operations": [{"op": "prepend_prefix", "field": "Material", "params": {"value": "PL"}}]}
    )
    _install(monkeypatch, client)
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert len(client.sent_payloads) == 1
    sent_intents = [node["intent"] for node in client.sent_payloads[0]["chain"]]
    assert sent_intents == ["transform"]  # the value_crosswalk node was excluded

    assert result["operations"] == [
        {"op": "prepend_prefix", "field": "Material", "params": {"value": "PL"}, "enabled": True}
    ]
    assert result["requires_value_pairing"] == [
        {"source_column": "Plant", "description": "Map plant codes via the code table", "row_index": 1}
    ]


def test_compile_deterministic_operations_dedupes_crosswalk_field_across_nodes(monkeypatch, llm_configured):
    chain = [
        {"step": 1, "intent": "value_crosswalk", "description": "Map plant codes (pass 1)", "row_indices": [0]},
        {"step": 2, "intent": "value_crosswalk", "description": "Map plant codes (pass 2)", "row_indices": [0]},
    ]
    enriched = [{"row_index": 0, "source_column": "Plant", "source_table": None, "datatype": None, "description": None}]
    result = mr.compile_deterministic_operations(chain, enriched, _SOURCE_COLUMNS)

    assert len(result["requires_value_pairing"]) == 1
    assert result["requires_value_pairing"][0]["description"] == "Map plant codes (pass 1)"


# ── orchestrator ─────────────────────────────────────────────────────────────

def test_resolve_mapping_chains_all_four_steps(monkeypatch, llm_configured):
    payloads = [
        {"relevant_row_indices": [0, 1]},
        {
            "enriched_fields": [
                {"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": "Material number"},
                {"row_index": 1, "source_column": "Plant", "source_table": "VBAP",
                 "datatype": None, "description": "Plant code"},
            ]
        },
        {
            "chain": [
                {"intent": "transform", "description": "Prepend PL to Material", "row_indices": [0]},
                {"intent": "filter", "description": "Keep Sales Org 5875 rows", "row_indices": [1]},
            ]
        },
        {
            "operations": [
                {"op": "prepend_prefix", "field": "Material", "params": {"value": "PL"}},
                {"op": "include_value", "field": "SalesOrg", "params": {"values": ["5875"]}},
            ]
        },
    ]
    _install(monkeypatch, _SequencedClient(payloads))

    result = mr.resolve_mapping(_MAPPING_SHEET, _SOURCE_COLUMNS, _TARGET_COLUMNS)

    assert result["degraded"] is False
    assert [c["row_index"] for c in result["relevant_fields"]] == [0, 1]
    assert len(result["enriched_fields"]) == 2
    assert len(result["transformation_chain"]) == 2
    assert result["transformation_chain"][0]["step"] == 1
    assert [op["op"] for op in result["operations"]] == ["prepend_prefix", "include_value"]
    assert result["proposed_operations"] == []


def test_resolve_mapping_no_llm_configured_degrades(monkeypatch):
    monkeypatch.setattr(mr, "get_settings", lambda: type("S", (), {"any_llm_configured": False})())
    result = mr.resolve_mapping(_MAPPING_SHEET, _SOURCE_COLUMNS, _TARGET_COLUMNS)

    assert result["degraded"] is True
    assert result["operations"] == []
    assert result["proposed_operations"] == []
    assert result["requires_value_pairing"] == []


def test_resolve_mapping_surfaces_requires_value_pairing(monkeypatch, llm_configured):
    payloads = [
        {"relevant_row_indices": [0, 1]},
        {
            "enriched_fields": [
                {"row_index": 0, "source_column": "Material", "source_table": "VBAP",
                 "datatype": None, "description": "Material number"},
                {"row_index": 1, "source_column": "Plant", "source_table": "VBAP",
                 "datatype": None, "description": "Plant code"},
            ]
        },
        {
            "chain": [
                {"intent": "value_crosswalk", "description": "Map plant codes via the code table", "row_indices": [1]},
            ]
        },
        # Step 4's LLM is never called here — the chain is crosswalk-only.
    ]
    _install(monkeypatch, _SequencedClient(payloads))

    result = mr.resolve_mapping(_MAPPING_SHEET, _SOURCE_COLUMNS, _TARGET_COLUMNS)

    assert result["operations"] == []
    assert result["requires_value_pairing"] == [
        {"source_column": "Plant", "description": "Map plant codes via the code table", "row_index": 1}
    ]
