"""Start the TradeArena API server."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "tradearena.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["src", "scripts"],
    )
