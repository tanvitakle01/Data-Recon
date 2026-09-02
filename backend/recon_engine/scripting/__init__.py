"""Script-transformation flow: Transformation Preview → User Approval.

Feature-flagged alternative (``USE_SCRIPT_TRANSFORMATIONS``) to the
contract-based compile/validate/approve flow. The pipeline is:

    Parsed Mapping JSON → Generator (Azure AI Foundry → deterministic fallback)
        → TransformationScript → Static Validation (AST allow-list)
        → Sandbox Execution → Transformation Preview
        → User approves the transformed DATA (not the code)
        → Production Execution (hash-pinned script) → Shadow_Source
        → existing deterministic reconciliation (unchanged)

Where the contract flow's invariant is "LLM output = data, engine output =
execution", this flow's invariant is layered instead: the LLM's script is
inert until it passes the static gate, runs only inside the restricted
sandbox namespace, and reaches production only when a human has approved its
*output data* — with the approval pinning the exact script hash that produced
the approved preview.
"""

from backend.recon_engine.scripting.generator import generate_script
from backend.recon_engine.scripting.models import (
    GeneratedBy,
    PreviewStatus,
    ScriptApproval,
    ScriptPreview,
    TransformationScript,
    script_sha256,
)
from backend.recon_engine.scripting.sandbox import (
    SandboxResult,
    ScriptExecutionError,
    execute_script,
)
from backend.recon_engine.scripting.validator import ScriptValidationReport, validate_script

__all__ = [
    "GeneratedBy",
    "PreviewStatus",
    "SandboxResult",
    "ScriptApproval",
    "ScriptExecutionError",
    "ScriptPreview",
    "ScriptValidationReport",
    "TransformationScript",
    "execute_script",
    "generate_script",
    "script_sha256",
    "validate_script",
]
