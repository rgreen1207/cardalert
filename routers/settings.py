import asyncio
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse

import config
import db
import notifier
import updater
from templating import templates
from view_helpers import common_context

router = APIRouter()


@router.get("/settings")
async def settings_page(request: Request, saved: Optional[str] = None):
    ctx = await common_context(request, "settings")
    ctx.update(
        values=await config.all_values(),
        saved=saved,
        currencies=list(config.CURRENCY_SYMBOLS.keys()),
        current_version=await asyncio.to_thread(updater.current_ref),
        pokemon_center_fast_check_floor=config.POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS,
        pokemon_center_repeat_alert_floor=config.POKEMON_CENTER_REPEAT_ALERT_FLOOR_SECONDS,
    )
    return templates.TemplateResponse("settings.html", ctx)


@router.post("/settings/save")
async def settings_save(
    discord_webhook_url: str = Form(""),
    discord_mention_users: str = Form(""),
    discord_mention_roles: str = Form(""),
    ntfy_topic: str = Form(""),
    pushover_user_key: str = Form(""),
    pushover_app_token: str = Form(""),
    twilio_account_sid: str = Form(""),
    twilio_auth_token: str = Form(""),
    twilio_from_number: str = Form(""),
    twilio_to_number: str = Form(""),
    bestbuy_api_key: str = Form(""),
    target_api_key: str = Form(""),
    pokemon_center_fast_check_seconds: str = Form("15"),
    pokemon_center_repeat_alerts: str = Form(""),
    pokemon_center_repeat_alert_seconds: str = Form("90"),
    currency: str = Form("USD"),
    dashboard_password: str = Form(""),
):
    for key, value in {
        "discord_webhook_url": discord_webhook_url,
        "discord_mention_users": discord_mention_users,
        "discord_mention_roles": discord_mention_roles,
        "ntfy_topic": ntfy_topic,
        "pushover_user_key": pushover_user_key,
        "pushover_app_token": pushover_app_token,
        "twilio_account_sid": twilio_account_sid,
        "twilio_auth_token": twilio_auth_token,
        "twilio_from_number": twilio_from_number,
        "twilio_to_number": twilio_to_number,
        "bestbuy_api_key": bestbuy_api_key,
        "target_api_key": target_api_key,
        "currency": currency,
    }.items():
        await config.set(key, value)
    try:
        clamped = max(int(pokemon_center_fast_check_seconds), config.POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS)
    except (TypeError, ValueError):
        clamped = config.POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS
    await config.set("pokemon_center_fast_check_seconds", str(clamped))

    await config.set("pokemon_center_repeat_alerts", "1" if pokemon_center_repeat_alerts else "")
    try:
        repeat_clamped = max(int(pokemon_center_repeat_alert_seconds), config.POKEMON_CENTER_REPEAT_ALERT_FLOOR_SECONDS)
    except (TypeError, ValueError):
        repeat_clamped = config.POKEMON_CENTER_REPEAT_ALERT_FLOOR_SECONDS
    await config.set("pokemon_center_repeat_alert_seconds", str(repeat_clamped))

    if dashboard_password:
        # blank field on the settings page means "leave unchanged." The
        # stored hash is never rendered back into the form to fill this in
        await config.set_dashboard_password(dashboard_password)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/settings/test-discord")
async def test_discord():
    result = await notifier.send_discord("🔔 Test alert from Card Alert. If you see this, your Discord webhook works.")
    # Report exactly what mentions (if any) were actually applied, so the
    # settings page can show it — this makes "did my mention settings even
    # get read correctly" verifiable from the UI instead of a guess.
    raw_users = await config.get("discord_mention_users")
    raw_roles = await config.get("discord_mention_roles")
    valid_users = notifier._parse_mention_ids(raw_users)
    valid_roles = notifier._parse_mention_ids(raw_roles)
    total_entries = len([p for p in raw_users.split(",") if p.strip()]) + \
        len([p for p in raw_roles.split(",") if p.strip()])
    valid_count = len(valid_users) + len(valid_roles)

    if valid_count:
        parts = []
        if valid_users:
            parts.append(f"{len(valid_users)} user{'s' if len(valid_users) != 1 else ''}")
        if valid_roles:
            parts.append(f"{len(valid_roles)} role{'s' if len(valid_roles) != 1 else ''}")
        result["mention_applied"] = " and ".join(parts)
        if valid_count < total_entries:
            result["mention_skipped_reason"] = (
                f"{total_entries - valid_count} entry/entries weren't purely numeric "
                "and were skipped rather than sent as broken text."
            )
    elif total_entries:
        result["mention_applied"] = None
        result["mention_skipped_reason"] = "None of the saved IDs were purely numeric, so all were skipped rather than sent as broken text."
    else:
        result["mention_applied"] = None
    return JSONResponse(result)


@router.post("/settings/discover-target-key")
async def discover_target_key():
    import pollers
    retailers = await db.list_retailers_for_polling(active_only=False)
    candidate_tcins = [r["identifier"] for r in retailers if r["retailer"] == "target"]
    key = await pollers.discover_target_api_key(candidate_tcins=candidate_tcins)
    if key:
        return JSONResponse({"ok": True, "key": key})
    return JSONResponse({"ok": False, "error": "Couldn't find one automatically — paste one in manually instead."})


@router.get("/settings/check-update")
async def check_update():
    return await asyncio.to_thread(updater.check_for_update)


@router.post("/settings/apply-update")
async def apply_update():
    return await asyncio.to_thread(updater.apply_update)
