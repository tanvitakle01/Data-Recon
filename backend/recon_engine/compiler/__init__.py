"""Contract compilers (compile phase).

A compiler produces contract JSON only — never code, never execution.

* ``GroqContractCompiler`` — LLM compile phase (name kept for backward
  compatibility; runs on Azure AI Foundry — needs AZURE_FOUNDRY_MODEL).
* ``StubContractCompiler``  — deterministic placeholder; makes the lifecycle
  runnable/testable today.
"""

from backend.recon_engine.compiler.base import ContractCompiler, ContractCompilerError
from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler
from backend.recon_engine.compiler.stub_compiler import StubContractCompiler

__all__ = [
    "ContractCompiler",
    "ContractCompilerError",
    "GroqContractCompiler",
    "StubContractCompiler",
]
