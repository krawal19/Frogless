"""python -m frogless.web: serve the page and the API at http://127.0.0.1:7860."""

import gradio as gr
import uvicorn

from .api import create_api
from .ui import CSS, THEME, build_ui

HOST, PORT = "127.0.0.1", 7860


def create_app():
    app = create_api()
    return gr.mount_gradio_app(app, build_ui(), path="/", theme=THEME, css=CSS, ssr_mode=False)


def main() -> None:
    print(f"Frogless is at http://{HOST}:{PORT}")
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
