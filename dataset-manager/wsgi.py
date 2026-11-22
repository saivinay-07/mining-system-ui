"""Production WSGI entry point used by Gunicorn on Render."""
from app import app, init

init()
