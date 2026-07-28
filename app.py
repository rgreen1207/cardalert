"""
This file wires everything together and nothing else. Every actual route
lives in routers/, grouped by the page/service it belongs to:
  routers/dashboard.py  - the monitoring page + pattern analytics
  routers/products.py   - product management, item CRUD, Shopify verifier
  routers/settings.py   - credentials, currency, password, self-updater
  routers/setup.py      - the first-run wizard
  routers/help.py       - the FAQ page
  routers/api.py        - the JSON /api/items endpoint

Adding a new page should mean adding a new router module and one
include_router() call below, not growing this file.
"""
import base64

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.responses import Response

import db
import scheduler
import config
from routers import dashboard, products, settings, setup, help as help_router, api

app = FastAPI(title="Card Alert")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(setup.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(settings.router)
app.include_router(help_router.router)
app.include_router(api.router)

_EXEMPT_FROM_SETUP_REDIRECT = {"/setup", "/setup/save", "/setup/skip"}


@app.middleware("http")
async def require_setup(request: Request, call_next):
    path = request.url.path
    if (
        not path.startswith("/static")
        and path not in _EXEMPT_FROM_SETUP_REDIRECT
        and not await config.is_setup_complete()
    ):
        return RedirectResponse("/setup")
    return await call_next(request)


@app.middleware("http")
async def require_dashboard_password(request: Request, call_next):
    if not await config.dashboard_password_is_set():
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, _, supplied_password = decoded.partition(":")
            if await config.check_dashboard_password(supplied_password):
                return await call_next(request)
        except (ValueError, UnicodeDecodeError):
            pass  # malformed Authorization header, falls through to 401 below
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Card Alert"'},
        content="Password required.",
    )


@app.on_event("startup")
async def startup():
    await db.init_db()
    scheduler.start()
