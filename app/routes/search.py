from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.services.search_service import MIN_QUERY_LEN, global_search

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    results = global_search(db, user, q)
    return request.app.state.templates.TemplateResponse(
        request,
        "search.html",
        {
            "user": user,
            "results": results,
            "min_query_len": MIN_QUERY_LEN,
        },
    )
