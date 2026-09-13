"""Versioned contract store (in-memory).

Contracts are versioned per ``contract_id``; a new version is an append. The
runtime engine only ever loads an APPROVED version. Nothing here mutates a
version's body after write — an "edit" is a new version.
"""

from __future__ import annotations

from backend.recon_engine.models.contract import ApprovalStatus, TransformationContract

_CONTRACTS: dict[tuple[str, int], TransformationContract] = {}


def next_version(contract_id: str) -> int:
    versions = [v for (cid, v) in _CONTRACTS if cid == contract_id]
    return (max(versions) + 1) if versions else 1


def save_contract(contract: TransformationContract) -> TransformationContract:
    """Insert a contract version row. Raises if that (id, version) exists."""
    key = (contract.contract_id, contract.contract_version)
    if key in _CONTRACTS:
        raise ValueError(f"Contract {key} already exists.")
    _CONTRACTS[key] = contract
    return contract


def get_contract(contract_id: str, version: int) -> TransformationContract | None:
    return _CONTRACTS.get((contract_id, version))


def get_latest_approved(contract_id: str) -> TransformationContract | None:
    candidates = [
        c for (cid, _v), c in _CONTRACTS.items()
        if cid == contract_id and c.approval_status == ApprovalStatus.APPROVED
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.contract_version)


def list_versions(contract_id: str) -> list[TransformationContract]:
    versions = [c for (cid, _v), c in _CONTRACTS.items() if cid == contract_id]
    return sorted(versions, key=lambda c: c.contract_version)
