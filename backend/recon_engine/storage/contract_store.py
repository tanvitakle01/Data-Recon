"""Versioned contract store.

Contracts are versioned per ``contract_id``; a new version is an append. The
runtime engine only ever loads an APPROVED version. Nothing here mutates a
version's body after write — an "edit" is a new version.
"""

from __future__ import annotations

import json

from backend.recon_engine.models.contract import ApprovalStatus, TransformationContract
from backend.recon_engine.storage.db import main_db


def next_version(contract_id: str) -> int:
    with main_db() as conn:
        row = conn.execute(
            "SELECT MAX(contract_version) AS v FROM contracts WHERE contract_id = ?",
            (contract_id,),
        ).fetchone()
    current = row["v"] if row and row["v"] is not None else 0
    return int(current) + 1


def save_contract(contract: TransformationContract) -> TransformationContract:
    """Insert a contract version row. Raises if that (id, version) exists."""
    body = contract.model_dump(mode="json")
    with main_db() as conn:
        conn.execute(
            """INSERT INTO contracts
               (contract_id, contract_version, comparison_type, source_type, target_type,
                approval_status, created_at, created_by, approved_at, approved_by,
                compiler, body_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                contract.contract_id, contract.contract_version, contract.comparison_type,
                contract.source_type, contract.target_type, contract.approval_status.value,
                contract.created_at.isoformat(), contract.created_by,
                contract.approved_at.isoformat() if contract.approved_at else None,
                contract.approved_by, contract.compiler, json.dumps(body),
            ),
        )
    return contract


def _row_to_contract(row) -> TransformationContract:
    return TransformationContract.model_validate(json.loads(row["body_json"]))


def get_contract(contract_id: str, version: int) -> TransformationContract | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT body_json FROM contracts WHERE contract_id = ? AND contract_version = ?",
            (contract_id, version),
        ).fetchone()
    return _row_to_contract(row) if row else None


def get_latest_approved(contract_id: str) -> TransformationContract | None:
    with main_db() as conn:
        row = conn.execute(
            """SELECT body_json FROM contracts
               WHERE contract_id = ? AND approval_status = ?
               ORDER BY contract_version DESC LIMIT 1""",
            (contract_id, ApprovalStatus.APPROVED.value),
        ).fetchone()
    return _row_to_contract(row) if row else None


def list_versions(contract_id: str) -> list[TransformationContract]:
    with main_db() as conn:
        rows = conn.execute(
            "SELECT body_json FROM contracts WHERE contract_id = ? ORDER BY contract_version",
            (contract_id,),
        ).fetchall()
    return [_row_to_contract(r) for r in rows]
