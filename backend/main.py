import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# TEMP DIAGNOSTIC (422 investigation on /api/recon/contracts/compile) — remove
# this logger + the handler below once the root cause is confirmed and fixed.
logging.basicConfig(level=logging.INFO)
_diag_log = logging.getLogger("recon.diagnostics")


def _load_env_file() -> None:
    """Load a backend .env into the environment (existing vars win).

    GROQ_API_KEY lives there; without it the contract compile phase silently
    falls back to the stub compiler. Minimal stdlib parser — avoids adding a
    python-dotenv dependency.

    We accept the file at either ``backend/.env`` (canonical) or
    ``backend/recon_engine/.env`` (where the recon engine's own config lives),
    loading whichever exist so a key placed in either spot is honoured.
    """
    backend_dir = Path(__file__).resolve().parent
    candidates = (backend_dir / ".env", backend_dir / "recon_engine" / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()

from backend.routes.preview import router as preview_router
from backend.routes.automap import router as automap_router
from backend.routes.s4_test_preview import router as s4_test_preview_router
from backend.routes.reconcile import router as reconcile_router
from backend.routes.files import router as files_router
from backend.routes.insights import router as insights_router
from backend.routes.ibp_test_preview import router as ibp_test_preview_router
from backend.routes.ibp_metadata import router as ibp_metadata_router
from backend.routes.s4_metadata import router as s4_metadata_router
from backend.routes.date_alignment_preview import router as date_alignment_preview_router
from backend.routes.comparison_types import router as comparison_types_router
from backend.routes.contracts import router as contracts_router
from backend.routes.value_mapping import router as value_mapping_router
from backend.routes.value_pairs import router as value_pairs_router
from backend.routes.mapping_infer import router as mapping_infer_router
from backend.routes.entity_join import router as entity_join_router
from backend.routes.library import router as library_router
from backend.routes.recon_v2 import router as recon_v2_router
from backend.routes.script_transformations import router as script_transformations_router
from backend.routes.auto_pipeline import router as auto_pipeline_router
from backend.recon_engine.storage.db import init_storage

app = FastAPI()


@app.on_event("startup")
def _init_recon_storage() -> None:
    # Create the persistent store (recon.db, recon_shadow.db + data dirs) if
    # absent. Idempotent — replaces the previous in-memory-only design.
    init_storage()


# TEMP DIAGNOSTIC — logs the raw request body and the exact Pydantic errors
# (field, location, message, type) for EVERY request-validation 422 across the
# whole app, then returns the identical default FastAPI response so client
# behaviour is unchanged. This is the only way to see a 422 the browser
# triggers but a hand-built TestClient payload does not reproduce. Remove once
# the /api/recon/contracts/compile 422 root cause is found and fixed.
@app.exception_handler(RequestValidationError)
async def _diagnostic_validation_error_handler(request: Request, exc: RequestValidationError):
    raw_body = await request.body()
    _diag_log.info(
        "422 VALIDATION FAILURE %s %s\n  raw body: %s\n  errors: %s",
        request.method,
        request.url.path,
        raw_body.decode("utf-8", errors="replace"),
        [
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg"),
                "type": err.get("type"),
                "input": err.get("input"),
            }
            for err in exc.errors()
        ],
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

app.add_middleware(
    CORSMiddleware,

    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(preview_router)
app.include_router(automap_router)

app.include_router(s4_test_preview_router)
app.include_router(ibp_test_preview_router)
app.include_router(ibp_metadata_router)
app.include_router(s4_metadata_router)
app.include_router(reconcile_router)
app.include_router(files_router)
app.include_router(insights_router)
app.include_router(date_alignment_preview_router)
app.include_router(comparison_types_router)
app.include_router(contracts_router)
app.include_router(value_mapping_router)
app.include_router(value_pairs_router)
app.include_router(mapping_infer_router)
app.include_router(library_router)
app.include_router(recon_v2_router)
app.include_router(script_transformations_router)
app.include_router(auto_pipeline_router)












