from app import create_app

# Gunicorn entrypoint: `wsgi:app`
app = create_app()
