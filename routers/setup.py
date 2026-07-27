from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import config
from templating import templates
from view_helpers import DONATE_URL

router = APIRouter()


@router.get("/setup")
def setup_wizard(request: Request):
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "values": config.all_values(),
        "donate_url": DONATE_URL,
    })


@router.post("/setup/save")
def setup_save(
    discord_webhook_url: str = Form(""),
    ntfy_topic: str = Form(""),
    pushover_user_key: str = Form(""),
    pushover_app_token: str = Form(""),
    twilio_account_sid: str = Form(""),
    twilio_auth_token: str = Form(""),
    twilio_from_number: str = Form(""),
    twilio_to_number: str = Form(""),
    bestbuy_api_key: str = Form(""),
    dashboard_password: str = Form(""),
):
    for key, value in {
        "discord_webhook_url": discord_webhook_url,
        "ntfy_topic": ntfy_topic,
        "pushover_user_key": pushover_user_key,
        "pushover_app_token": pushover_app_token,
        "twilio_account_sid": twilio_account_sid,
        "twilio_auth_token": twilio_auth_token,
        "twilio_from_number": twilio_from_number,
        "twilio_to_number": twilio_to_number,
        "bestbuy_api_key": bestbuy_api_key,
    }.items():
        if value:
            config.set(key, value)
    if dashboard_password:
        config.set_dashboard_password(dashboard_password)
    config.mark_setup_complete()
    return RedirectResponse("/products", status_code=303)


@router.post("/setup/skip")
def setup_skip():
    config.mark_setup_complete()
    return RedirectResponse("/products", status_code=303)
