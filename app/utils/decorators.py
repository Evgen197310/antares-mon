from functools import wraps
from flask import session, redirect, url_for, flash, request


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # AUTH DISABLED: allow all
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # AUTH DISABLED: allow all
        return view(*args, **kwargs)
    return wrapped


def require_section(section_name: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            # AUTH DISABLED: allow all
            return view(*args, **kwargs)
        return wrapped
    return decorator
