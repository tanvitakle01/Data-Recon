import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)


def _load_env_file() -> None:
    """Load a backend .env into the environment (existing vars win).

    AZURE_FOUNDRY_MODEL / AZURE_FOUNDRY_BASE_URL live here for local dev;
    without them the LLM call path fails loudly rather than silently
    degrading. Minimal stdlib parser — avoids adding a python-dotenv
    dependency. Only ``backend/recon_engine/.env`` is read now — this is the
    only place the app's own config lives (no auth/DB .env anymore).
    """
    backend_dir = Path(__file__).resolve().parent
    env_path = backend_dir / "recon_engine" / ".env"
    if not env_path.is_file():
        return
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
from backend.routes.reconcile import router as reconcile_router
from backend.routes.files import router as files_router
from backend.routes.date_alignment_preview import router as date_alignment_preview_router
from backend.routes.contracts import router as contracts_router
from backend.routes.value_mapping import router as value_mapping_router
from backend.routes.value_pairs import router as value_pairs_router
from backend.routes.mapping_infer import router as mapping_infer_router
from backend.routes.recon_v2 import router as recon_v2_router
from backend.routes.script_transformations import router as script_transformations_router

logger = logging.getLogger("recon.main")

app = FastAPI()


# TEMP DIAGNOSTIC — logs the raw request body and the exact Pydantic errors
# (field, location, message, type) for EVERY request-validation 422 across the
# whole app, then returns the identical default FastAPI response so client
# behaviour is unchanged. Remove once the /api/recon/contracts/compile 422
# root cause is found and fixed.
_diag_log = logging.getLogger("recon.diagnostics")


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
app.include_router(reconcile_router)
app.include_router(files_router)
app.include_router(date_alignment_preview_router)
app.include_router(contracts_router)
app.include_router(value_mapping_router)
app.include_router(value_pairs_router)
app.include_router(mapping_infer_router)
app.include_router(recon_v2_router)
app.include_router(script_transformations_router)
