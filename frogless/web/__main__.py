"""python -m frogless.web: serve the page and the API at http://127.0.0.1:7860."""

import uvicorn

from .api import create_api

HOST, PORT = "127.0.0.1", 7860


def create_app():
    return create_api()


def main() -> None:
    print(f"Frogless is at http://{HOST}:{PORT}")
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
