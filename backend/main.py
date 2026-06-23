from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.preview import router as preview_router

from backend.routes.reconcile import router as reconcile_router

from backend.routes.sap_preview import router as sap_preview_router
from backend.routes.automap import router as automap_router
from backend.routes.s4_test_preview import router as s4_test_preview_router
from backend.routes.ibp_test_preview import router as ibp_test_preview_router


app = FastAPI()




app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(preview_router)

app.include_router(reconcile_router)
app.include_router(sap_preview_router)
app.include_router(automap_router)

app.include_router(s4_test_preview_router)











