"""Start the admin with Gunicorn; use one process for login rate limiting."""

from gunicorn.app.base import BaseApplication

from .config import load_config
from .web import create_app


class Admin(BaseApplication):
    def __init__(self):
        self.settings = load_config()
        super().__init__()

    def load_config(self):
        for key, value in {"bind": f'{self.settings["ADMIN_BIND"]}:{self.settings["ADMIN_PORT"]}',
                           "workers": 1, "threads": 4, "accesslog": "-", "errorlog": "-",
                           "timeout": 30}.items():
            self.cfg.set(key, value)

    def load(self):
        return create_app(config=self.settings)


if __name__ == "__main__":
    Admin().run()
