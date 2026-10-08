from typing import Dict, Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.analytics_service import (
    get_dashboard_summary_metrics,
    get_calls_by_territory,
    get_doctor_visit_frequency,
    get_calls_by_visit_type,
    get_daily_activity_trend,
    get_referral_funnel,
    get_indication_therapy_breakdown,
    get_product_demand,
    get_marketer_scorecard,
    get_doctor_coverage,
    get_follow_up_control,
    get_territory_performance,
    get_market_intelligence,
)

router = APIRouter(prefix="/dashboard", tags=["Analytics & Reporting"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Render role-scoped analytics for marketers and global analytics for managers/admins."""
    user_id = current_user.id if current_user.role == "marketer" else None
    metrics = get_dashboard_summary_metrics(db, user_id=user_id)
    territory_breakdown = get_calls_by_territory(db, user_id=user_id)
    doctor_frequency = get_doctor_visit_frequency(db, limit=8, user_id=user_id)
    visit_type_breakdown = get_calls_by_visit_type(db, user_id=user_id)
    daily_trend = get_daily_activity_trend(db, days=7, user_id=user_id)
    referral_funnel = get_referral_funnel(db, user_id=user_id)
    indication_breakdown = get_indication_therapy_breakdown(db, user_id=user_id)
    product_demand = get_product_demand(db, user_id=user_id)
    marketer_scorecard = get_marketer_scorecard(db, user_id=user_id)
    doctor_coverage = get_doctor_coverage(db, user_id=user_id)
    follow_up_control = get_follow_up_control(db, user_id=user_id)
    territory_performance = get_territory_performance(db, user_id=user_id)
    market_intelligence = get_market_intelligence(db, user_id=user_id)

    # Calculate max trend for scaling CSS bar heights
    max_trend_count = max([t["count"] for t in daily_trend], default=1) or 1
    max_referral_count = max(
        [item["opportunity_count"] for item in referral_funnel["statuses"]],
        default=1
    ) or 1
    max_indication_count = max(
        [item["call_count"] for item in indication_breakdown],
        default=1
    ) or 1
    max_product_count = max([item["call_count"] for item in product_demand], default=1) or 1

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": current_user,
            "metrics": metrics,
            "territory_breakdown": territory_breakdown,
            "doctor_frequency": doctor_frequency,
            "visit_type_breakdown": visit_type_breakdown,
            "daily_trend": daily_trend,
            "max_trend_count": max_trend_count,
            "referral_funnel": referral_funnel,
            "indication_breakdown": indication_breakdown,
            "product_demand": product_demand,
            "marketer_scorecard": marketer_scorecard,
            "doctor_coverage": doctor_coverage,
            "follow_up_control": follow_up_control,
            "territory_performance": territory_performance,
            "market_intelligence": market_intelligence,
            "max_referral_count": max_referral_count,
            "max_indication_count": max_indication_count,
            "max_product_count": max_product_count,
        }
    )


@router.get("/api/metrics", response_class=JSONResponse)
async def dashboard_metrics_api(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return JSON metrics for dashboard analytics."""
    user_id = current_user.id if current_user.role == "marketer" else None
    return {
        "metrics": get_dashboard_summary_metrics(db, user_id=user_id),
        "calls_by_territory": get_calls_by_territory(db, user_id=user_id),
        "doctor_frequency": get_doctor_visit_frequency(db, user_id=user_id),
        "calls_by_visit_type": get_calls_by_visit_type(db, user_id=user_id),
        "daily_trend": get_daily_activity_trend(db, days=7, user_id=user_id),
        "referral_funnel": get_referral_funnel(db, user_id=user_id),
        "indication_therapy": get_indication_therapy_breakdown(db, user_id=user_id),
        "product_demand": get_product_demand(db, user_id=user_id),
        "marketer_scorecard": get_marketer_scorecard(db, user_id=user_id),
        "doctor_coverage": get_doctor_coverage(db, user_id=user_id),
        "follow_up_control": get_follow_up_control(db, user_id=user_id),
        "territory_performance": get_territory_performance(db, user_id=user_id),
        "market_intelligence": get_market_intelligence(db, user_id=user_id),
    }
