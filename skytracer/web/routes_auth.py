from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from skytracer import settings_store
from skytracer.web import auth
from skytracer.web.deps import ADMIN_PASSWORD_KEY, ConnDep, has_admin_password
from skytracer.web.templating import templates

router = APIRouter()


@router.get("/setup")
def setup_form(request: Request, conn: ConnDep):
    if has_admin_password(conn):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "setup.html", {"logged_in": False, "error": None}
    )


@router.post("/setup")
def setup_submit(
    request: Request,
    conn: ConnDep,
    password: str = Form(...),
    confirm: str = Form(...),
):
    if has_admin_password(conn):
        return RedirectResponse("/login", status_code=303)

    error = None
    if len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm:
        error = "Passwords don't match."

    if error:
        return templates.TemplateResponse(
            request, "setup.html", {"logged_in": False, "error": error}, status_code=400
        )

    settings_store.set(conn, ADMIN_PASSWORD_KEY, auth.hash_password(password))
    response = RedirectResponse("/settings", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_cookie(conn),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/login")
def login_form(request: Request, conn: ConnDep):
    if not has_admin_password(conn):
        return RedirectResponse("/setup", status_code=303)
    if auth.is_logged_in(conn, request):
        return RedirectResponse("/settings", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"logged_in": False, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    conn: ConnDep,
    password: str = Form(...),
):
    key = auth.client_key(request)
    if auth.is_rate_limited(key):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"logged_in": False, "error": "Too many failed attempts. Try again in a few minutes."},
            status_code=429,
        )

    stored_hash = settings_store.get(conn, ADMIN_PASSWORD_KEY, "")
    if not stored_hash or not auth.verify_password(password, stored_hash):
        auth.record_failed_login(key)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"logged_in": False, "error": "Incorrect password."},
            status_code=401,
        )

    auth.clear_failed_logins(key)
    response = RedirectResponse("/settings", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_cookie(conn),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response
