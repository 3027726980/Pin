from backend.api.v1.auth import router as auth_router
from backend.api.v1.knowledge import router as knowledge_router
from backend.api.v1.model_config import router as model_config_router

__all__ = ["auth_router", "knowledge_router", "model_config_router"]
