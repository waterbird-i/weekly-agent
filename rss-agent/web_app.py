"""Entry point for RSS Agent dashboard."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "src.webui.app:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )
