from pathlib import Path

import uvicorn

from service.app import create_app


if __name__ == "__main__":
    app = create_app(Path.cwd() / ".runtime")
    uvicorn.run(app, host="127.0.0.1", port=8000)
