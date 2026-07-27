from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse

import config
import notifier
import updater
from templating import templates
from view_helpers import common_context

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request, saved: Optional[str] = None):
    ctx = common_context(request, "settings")
    ctx.update(
        values=config.all_values(),
        saved=saved,
        currencies=list(config.CURRENCY_SYMBOLS.keys()),
        current_version=updater.current_ref(),
    )
    return templates.TemplateResponse("settings.html", ctx)


@router.post("/settings/save")
def settings_save(
    discord_webhook_url: str = Form(""),
    discord_mention_type: str = Form(""),
    discord_mention_id: str = Form(""),
    ntfy_topic: str = Form(""),
    pushover_user_key: str = Form(""),
    pushover_app_token: str = Form(""),
    twilio_account_sid: str = Form(""),
    twilio_auth_token: str = Form(""),
    twilio_from_number: str = Form(""),
    twilio_to_number: str = Form(""),
    bestbuy_api_key: str = Form(""),
    currency: str = Form("USD"),
    dashboard_password: str = Form(""),
):
    for key, value in {
        "discord_webhook_url": discord_webhook_url,
        "discord_mention_type": discord_mention_type,
        "discord_mention_id": discord_mention_id,
        "ntfy_topic": ntfy_topic,
        "pushover_user_key": pushover_user_key,
        "pushover_app_token": pushover_app_token,
        "twilio_account_sid": twilio_account_sid,
        "twilio_auth_token": twilio_auth_token,
        "twilio_from_number": twilio_from_number,
        "twilio_to_number": twilio_to_number,
        "bestbuy_api_key": bestbuy_api_key,
        "currency": currency,
    }.items():
        config.set(key, value)
    if dashboard_password:
        # blank field on the settings page means "leave unchanged." The
        # stored hash is never rendered back into the form to fill this in
        config.set_dashboard_password(dashboard_password)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/settings/test-discord")
def test_discord():
    result = notifier.send_discord("🔔 Test alert from Card Alert. If you see this, your Discord webhook works.")
    return JSONResponse(result)


@router.get("/settings/check-update")
def check_update():
    return updater.check_for_update()


@router.post("/settings/apply-update")
def apply_update():
    return updater.apply_update()
