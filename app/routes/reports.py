"""
Report routes — REST API for the customizable reporting engine.

All endpoints require admin/manager role except GET /api/reports/presets.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import io

from app.middleware.auth import get_current_user_with_role
from app.models.report import (
    ReportDefinition,
    ReportCreate,
    ReportUpdate,
    OutlierRequest,
    TrendRequest,
    ExportRequest,
)
from app.services.report_service import (
    run_report,
    run_outlier_report,
    run_trend_report,
    export_report,
    save_report,
    get_saved_reports,
    get_saved_report,
    update_saved_report,
    delete_saved_report,
    get_report_presets,
)

router = APIRouter(prefix="/api/reports", tags=["Reports"])


# ── Execute Reports ───────────────────────────────────────────────────────

@router.post("/run")
async def execute_report(
    definition: ReportDefinition,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Execute a report definition and return structured results.

    Send a report definition with dimensions, measures, filters, and chart
    type.  The backend dynamically builds a MongoDB aggregation pipeline
    and returns rows + column metadata + summary stats.
    """
    try:
        result = await run_report(definition)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report execution failed: {str(e)}")


@router.post("/export")
async def export_report_data(
    request: ExportRequest,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Execute a report and export the results as CSV, JSON, or PDF."""
    if request.format not in ("csv", "json", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'csv', 'json', or 'pdf'")

    try:
        result = await export_report(request.definition, request.format, request.title)

        if request.format == "csv":
            filename = result.get("filename", "report.csv")
            return StreamingResponse(
                io.StringIO(result.get("content", "")),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        if request.format == "pdf":
            filename = result.get("filename", "report.pdf")
            return StreamingResponse(
                io.BytesIO(result.get("content", b"")),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ── Outlier Detection ─────────────────────────────────────────────────────

@router.post("/outliers")
async def find_outliers(
    request: OutlierRequest,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Find contracts where a metric exceeds a threshold or deviates
    significantly from the mean.

    Use `threshold` for an absolute cutoff (e.g. risk_score > 75) or
    `std_deviations` for statistical outlier detection (e.g. 2σ above mean).
    """
    if request.field not in ("risk_score", "value"):
        raise HTTPException(
            status_code=400,
            detail="field must be 'risk_score' or 'value'",
        )
    if request.threshold is None and request.std_deviations is None:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'threshold' or 'std_deviations'",
        )

    try:
        result = await run_outlier_report(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Outlier detection failed: {str(e)}")


# ── Trend Analysis ────────────────────────────────────────────────────────

@router.post("/trends")
async def get_trends(
    request: TrendRequest,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get time-series trend data for line charts.

    Returns data points bucketed by month or quarter for the requested
    measure (count, total_value, avg_risk_score, etc.).
    """
    if request.interval not in ("month", "quarter"):
        raise HTTPException(
            status_code=400,
            detail="interval must be 'month' or 'quarter'",
        )

    try:
        result = await run_trend_report(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trend analysis failed: {str(e)}")


# ── Presets ───────────────────────────────────────────────────────────────

@router.get("/presets")
async def list_presets(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get pre-built report templates that can be used as starting points.

    Returns 10 commonly useful report definitions that administrators can
    run immediately or customize further.
    """
    return get_report_presets()


# ── Saved Report CRUD ─────────────────────────────────────────────────────

@router.get("/")
async def list_saved_reports(
    current_user: dict = Depends(get_current_user_with_role),
):
    """List all saved report definitions visible to the current user.

    Admins see all reports; regular users see their own + shared reports.
    """
    is_admin = current_user.get("role") in ("admin", "manager")
    reports = await get_saved_reports(
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    return reports


@router.post("/")
async def create_saved_report(
    report: ReportCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Save a named report definition for later re-use."""
    result = await save_report(report, user_id=current_user["user_id"])
    return result


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get a single saved report by ID."""
    is_admin = current_user.get("role") in ("admin", "manager")
    report = await get_saved_report(
        report_id,
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.put("/{report_id}")
async def update_report(
    report_id: str,
    update: ReportUpdate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Update a saved report definition."""
    is_admin = current_user.get("role") in ("admin", "manager")
    report = await update_saved_report(
        report_id,
        update,
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found or access denied")
    return report


@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Delete a saved report definition."""
    is_admin = current_user.get("role") in ("admin", "manager")
    deleted = await delete_saved_report(
        report_id,
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found or access denied")
    return {"message": "Report deleted successfully"}
