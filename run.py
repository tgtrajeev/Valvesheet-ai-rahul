"""Server launcher."""

import os
import uvicorn
from app.config import settings

if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.port))
    reload = os.environ.get("RENDER") is None  # disable reload in production
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)
