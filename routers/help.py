from fastapi import APIRouter, Request

from templating import templates
from view_helpers import common_context

router = APIRouter()


@router.get("/help")
def help_page(request: Request):
    ctx = common_context(request, "help")
    return templates.TemplateResponse("help.html", ctx)
