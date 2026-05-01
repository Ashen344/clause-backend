"""
Report Service — Customizable reporting engine for CLAUSE CLM.

Dynamically builds MongoDB aggregation pipelines from user-defined report
definitions.  Supports grouping by multiple dimensions, computing various
measures, filtering, outlier detection, time-series trends, and CSV export.
"""

import csv
import io
import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId

from app.config import contracts_collection, db
from app.models.report import (
    ReportDefinition,
    ReportDimension,
    ReportMeasure,
    ReportFilter,
    ReportColumn,
    ReportSummary,
    ReportResult,
    ReportChartType,
    ReportCreate,
    ReportUpdate,
    OutlierRequest,
    TrendRequest,
)

logger = logging.getLogger(__name__)

# The MongoDB collection for saved report definitions
reports_collection = db["reports"]


# ── Filter → $match ───────────────────────────────────────────────────────

def _build_match_stage(filters: Optional[ReportFilter]) -> dict:
    """Convert a ReportFilter into a MongoDB $match document."""
    match: dict = {}
    if not filters:
        return match

    # Date range on created_at
    if filters.date_from or filters.date_to:
        date_q: dict = {}
        if filters.date_from:
            date_q["$gte"] = filters.date_from
        if filters.date_to:
            date_q["$lte"] = filters.date_to
        match["created_at"] = date_q

    # Date range on end_date
    if filters.end_date_from or filters.end_date_to:
        end_q: dict = {}
        if filters.end_date_from:
            end_q["$gte"] = filters.end_date_from
        if filters.end_date_to:
            end_q["$lte"] = filters.end_date_to
        match["end_date"] = end_q

    # Multi-value enum filters (OR within each)
    if filters.contract_types:
        match["contract_type"] = {"$in": filters.contract_types}
    if filters.statuses:
        match["status"] = {"$in": filters.statuses}
    if filters.workflow_stages:
        match["workflow_stage"] = {"$in": filters.workflow_stages}
    if filters.risk_levels:
        match["ai_analysis.risk_level"] = {"$in": filters.risk_levels}
    if filters.tags:
        match["tags"] = {"$in": filters.tags}
    if filters.created_by:
        match["created_by"] = {"$in": filters.created_by}

    # Numeric range filters
    if filters.value_min is not None or filters.value_max is not None:
        val_q: dict = {}
        if filters.value_min is not None:
            val_q["$gte"] = filters.value_min
        if filters.value_max is not None:
            val_q["$lte"] = filters.value_max
        match["value"] = val_q

    if filters.risk_score_min is not None or filters.risk_score_max is not None:
        rs_q: dict = {}
        if filters.risk_score_min is not None:
            rs_q["$gte"] = filters.risk_score_min
        if filters.risk_score_max is not None:
            rs_q["$lte"] = filters.risk_score_max
        match["ai_analysis.risk_score"] = rs_q

    if filters.has_ai_analysis is True:
        match["ai_analysis"] = {"$ne": None}
    elif filters.has_ai_analysis is False:
        match["ai_analysis"] = None

    return match


# ── Dimensions → $group _id ───────────────────────────────────────────────

# Fields that need $addFields to be computed before grouping
_COMPUTED_DIMENSIONS = {
    ReportDimension.month: {
        "add_field": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}},
        "group_key": "$_computed_month",
    },
    ReportDimension.quarter: {
        "add_field": {
            "$concat": [
                {"$toString": {"$year": "$created_at"}},
                "-Q",
                {"$toString": {"$ceil": {"$divide": [{"$month": "$created_at"}, 3]}}},
            ]
        },
        "group_key": "$_computed_quarter",
    },
    ReportDimension.year: {
        "add_field": {"$toString": {"$year": "$created_at"}},
        "group_key": "$_computed_year",
    },
}

# Simple field dimensions — map directly to a document field
_SIMPLE_DIMENSION_FIELDS = {
    ReportDimension.contract_type: "$contract_type",
    ReportDimension.status: "$status",
    ReportDimension.workflow_stage: "$workflow_stage",
    ReportDimension.risk_level: "$ai_analysis.risk_level",
    ReportDimension.created_by: "$created_by",
    ReportDimension.tags: "$tags",
}


def _build_group_id(dimensions: list[ReportDimension]) -> dict | str | None:
    """Build the _id expression for a $group stage."""
    if not dimensions:
        return None  # single-group aggregation (totals only)

    if len(dimensions) == 1:
        dim = dimensions[0]
        if dim in _COMPUTED_DIMENSIONS:
            return _COMPUTED_DIMENSIONS[dim]["group_key"]
        return _SIMPLE_DIMENSION_FIELDS.get(dim, f"${dim.value}")

    # Multi-dimension: {dim1: "$field1", dim2: "$field2"}
    group_id = {}
    for dim in dimensions:
        if dim in _COMPUTED_DIMENSIONS:
            group_id[dim.value] = _COMPUTED_DIMENSIONS[dim]["group_key"]
        else:
            group_id[dim.value] = _SIMPLE_DIMENSION_FIELDS.get(dim, f"${dim.value}")
    return group_id


# ── Measures → $group accumulators ────────────────────────────────────────

_MEASURE_ACCUMULATORS = {
    ReportMeasure.count:          {"$sum": 1},
    ReportMeasure.total_value:    {"$sum": {"$ifNull": ["$value", 0]}},
    ReportMeasure.avg_value:      {"$avg": "$value"},
    ReportMeasure.min_value:      {"$min": "$value"},
    ReportMeasure.max_value:      {"$max": "$value"},
    ReportMeasure.avg_risk_score: {"$avg": "$ai_analysis.risk_score"},
    ReportMeasure.max_risk_score: {"$max": "$ai_analysis.risk_score"},
    ReportMeasure.min_risk_score: {"$min": "$ai_analysis.risk_score"},
}


def _build_group_accumulators(measures: list[ReportMeasure]) -> dict:
    """Build the accumulator fields for a $group stage."""
    accumulators = {}
    for measure in measures:
        accumulators[measure.value] = _MEASURE_ACCUMULATORS[measure]
    return accumulators


# ── Column Metadata ───────────────────────────────────────────────────────

_MEASURE_LABELS = {
    ReportMeasure.count:          ("Count", "number"),
    ReportMeasure.total_value:    ("Total Value", "number"),
    ReportMeasure.avg_value:      ("Avg Value", "number"),
    ReportMeasure.min_value:      ("Min Value", "number"),
    ReportMeasure.max_value:      ("Max Value", "number"),
    ReportMeasure.avg_risk_score: ("Avg Risk Score", "number"),
    ReportMeasure.max_risk_score: ("Max Risk Score", "number"),
    ReportMeasure.min_risk_score: ("Min Risk Score", "number"),
}

_DIMENSION_LABELS = {
    ReportDimension.contract_type:  "Contract Type",
    ReportDimension.status:         "Status",
    ReportDimension.workflow_stage: "Workflow Stage",
    ReportDimension.risk_level:     "Risk Level",
    ReportDimension.created_by:     "Created By",
    ReportDimension.month:          "Month",
    ReportDimension.quarter:        "Quarter",
    ReportDimension.year:           "Year",
    ReportDimension.tags:           "Tag",
}


def _build_columns(
    dimensions: list[ReportDimension],
    measures: list[ReportMeasure],
) -> list[ReportColumn]:
    """Build column metadata for the report result."""
    columns = []
    for dim in dimensions:
        columns.append(ReportColumn(
            key=dim.value,
            label=_DIMENSION_LABELS.get(dim, dim.value),
            type="string",
        ))
    for measure in measures:
        label, col_type = _MEASURE_LABELS.get(measure, (measure.value, "number"))
        columns.append(ReportColumn(
            key=measure.value,
            label=label,
            type=col_type,
        ))
    return columns


# ── Pipeline Builder ──────────────────────────────────────────────────────

def _build_pipeline(definition: ReportDefinition) -> list[dict]:
    """Build a complete MongoDB aggregation pipeline from a ReportDefinition."""
    pipeline: list[dict] = []

    # 1. $match — filter
    match = _build_match_stage(definition.filters)
    if match:
        pipeline.append({"$match": match})

    # 2. $unwind tags if grouping by tags
    if ReportDimension.tags in definition.dimensions:
        pipeline.append({"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": False}})

    # 3. $addFields — computed dimensions (month, quarter, year)
    add_fields = {}
    for dim in definition.dimensions:
        if dim in _COMPUTED_DIMENSIONS:
            field_name = f"_computed_{dim.value}"
            add_fields[field_name] = _COMPUTED_DIMENSIONS[dim]["add_field"]
    if add_fields:
        pipeline.append({"$addFields": add_fields})

    # 4. $group — dimensions + measures
    group_id = _build_group_id(definition.dimensions)
    group_stage = {"_id": group_id}
    group_stage.update(_build_group_accumulators(definition.measures))
    # Always track the count of matched contracts for the summary
    if ReportMeasure.count not in definition.measures:
        group_stage["_total_count"] = {"$sum": 1}
    pipeline.append({"$group": group_stage})

    # 5. $sort
    if definition.sort_by:
        sort_dir = 1 if definition.sort_order.value == "asc" else -1
        pipeline.append({"$sort": {definition.sort_by: sort_dir}})
    elif definition.dimensions:
        # Default: sort by first measure descending
        first_measure = definition.measures[0].value if definition.measures else "count"
        pipeline.append({"$sort": {first_measure: -1}})

    # 6. $limit
    if definition.limit:
        pipeline.append({"$limit": definition.limit})

    return pipeline


# ── Row Flattening ────────────────────────────────────────────────────────

def _flatten_row(
    raw: dict,
    dimensions: list[ReportDimension],
    measures: list[ReportMeasure],
) -> dict:
    """Convert a raw aggregation result document into a flat row dict."""
    row: dict = {}

    # Extract dimensions from _id
    group_id = raw.get("_id")
    if group_id is None:
        # No dimensions — totals row
        pass
    elif isinstance(group_id, dict):
        for dim in dimensions:
            row[dim.value] = group_id.get(dim.value)
    else:
        # Single dimension — _id is a scalar
        if dimensions:
            row[dimensions[0].value] = group_id

    # Extract measures
    for measure in measures:
        val = raw.get(measure.value)
        if val is not None and isinstance(val, float):
            val = round(val, 2)
        row[measure.value] = val

    return row


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


async def run_report(definition: ReportDefinition) -> ReportResult:
    """Execute a report definition and return structured results."""
    pipeline = _build_pipeline(definition)

    logger.info("Running report pipeline with %d stages", len(pipeline))
    logger.debug("Pipeline: %s", pipeline)

    raw_results = list(contracts_collection.aggregate(pipeline))

    # Flatten rows
    rows = [
        _flatten_row(r, definition.dimensions, definition.measures)
        for r in raw_results
    ]

    # Build column metadata
    columns = _build_columns(definition.dimensions, definition.measures)

    # Summary stats
    total_contracts = sum(
        r.get(ReportMeasure.count.value, r.get("_total_count", 0))
        for r in raw_results
    )
    summary_stats = {}
    for measure in definition.measures:
        values = [r.get(measure.value) for r in raw_results if r.get(measure.value) is not None]
        if values and measure != ReportMeasure.count:
            summary_stats[f"total_{measure.value}"] = round(sum(values), 2)

    summary = ReportSummary(
        total_rows=len(rows),
        total_contracts_matched=total_contracts,
        summary_stats=summary_stats,
    )

    return ReportResult(
        columns=columns,
        rows=rows,
        summary=summary,
        chart_type=definition.chart_type,
        generated_at=datetime.utcnow(),
    )


async def run_outlier_report(request: OutlierRequest) -> dict:
    """Find contracts where a metric exceeds a threshold or deviates
    significantly from the mean."""
    # Map user field names to MongoDB paths
    field_map = {
        "risk_score": "ai_analysis.risk_score",
        "value": "value",
    }
    db_field = field_map.get(request.field, request.field)

    # Base filter
    match = _build_match_stage(request.filters)
    match[db_field] = {"$ne": None}

    threshold = request.threshold

    # If using standard deviations, compute the mean + std first
    if request.std_deviations and threshold is None:
        stats_pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "avg": {"$avg": f"${db_field}"},
                    "std": {"$stdDevPop": f"${db_field}"},
                    "count": {"$sum": 1},
                }
            },
        ]
        stats_result = list(contracts_collection.aggregate(stats_pipeline))
        if stats_result:
            avg_val = stats_result[0].get("avg", 0)
            std_val = stats_result[0].get("std", 0)
            threshold = avg_val + (request.std_deviations * std_val)

    if threshold is None:
        threshold = 75.0  # sensible default for risk_score

    # Find outlier contracts
    match[db_field] = {"$gte": threshold}
    contracts = list(
        contracts_collection.find(match)
        .sort(db_field, -1)
        .limit(request.limit)
    )

    results = []
    for c in contracts:
        results.append({
            "id": str(c["_id"]),
            "title": c.get("title", "Untitled"),
            "contract_type": c.get("contract_type"),
            "status": c.get("status"),
            "value": c.get("value"),
            "risk_score": (c.get("ai_analysis") or {}).get("risk_score"),
            "risk_level": (c.get("ai_analysis") or {}).get("risk_level"),
            "created_at": c.get("created_at"),
            "end_date": c.get("end_date"),
        })

    return {
        "field": request.field,
        "threshold": round(threshold, 2),
        "outliers_found": len(results),
        "contracts": results,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def run_trend_report(request: TrendRequest) -> dict:
    """Generate time-series data for trend charts."""
    # Date range
    now = datetime.utcnow()
    start_date = now - timedelta(days=request.months * 30)

    match = _build_match_stage(request.filters)
    match["created_at"] = {"$gte": start_date}

    # Group by time interval
    if request.interval == "quarter":
        group_id = {
            "year": {"$year": "$created_at"},
            "quarter": {"$ceil": {"$divide": [{"$month": "$created_at"}, 3]}},
        }
    else:  # month
        group_id = {
            "year": {"$year": "$created_at"},
            "month": {"$month": "$created_at"},
        }

    # Build accumulator for the requested measure
    accumulator = _MEASURE_ACCUMULATORS.get(
        request.measure,
        {"$sum": 1},
    )

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": group_id,
                "value": accumulator,
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1} if request.interval == "month"
                  else {"_id.year": 1, "_id.quarter": 1}},
    ]

    raw_results = list(contracts_collection.aggregate(pipeline))

    data_points = []
    for r in raw_results:
        gid = r["_id"]
        if request.interval == "quarter":
            label = f"{gid['year']}-Q{gid['quarter']}"
        else:
            label = f"{gid['year']}-{gid['month']:02d}"

        val = r.get("value", 0)
        if isinstance(val, float):
            val = round(val, 2)

        data_points.append({
            "period": label,
            "value": val,
            "count": r.get("count", 0),
        })

    return {
        "measure": request.measure.value,
        "interval": request.interval,
        "months": request.months,
        "data_points": data_points,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _build_pdf(result: ReportResult, title: str = "CLAUSE Report") -> bytes:
    """Render a ReportResult to a PDF and return the raw bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    buf = io.BytesIO()
    page_size = landscape(A4) if len(result.columns) > 4 else A4
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "clause_title",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1e3a5f"),
        fontSize=16,
        spaceAfter=6,
    )
    footer_style = ParagraphStyle(
        "clause_footer",
        parent=styles["Normal"],
        alignment=TA_RIGHT,
        fontSize=8,
        textColor=colors.HexColor("#888888"),
    )

    elements = []

    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 0.3 * cm))

    summary_text = (
        f"<b>Rows:</b> {result.summary.total_rows} &nbsp;&nbsp; "
        f"<b>Contracts matched:</b> {result.summary.total_contracts_matched}"
    )
    if result.summary.summary_stats:
        extra = " &nbsp;&nbsp; ".join(
            f"<b>{k.replace('_', ' ').title()}:</b> {v:,.2f}" if isinstance(v, float)
            else f"<b>{k.replace('_', ' ').title()}:</b> {v}"
            for k, v in result.summary.summary_stats.items()
        )
        summary_text += f" &nbsp;&nbsp; {extra}"
    elements.append(Paragraph(summary_text, styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    if result.rows:
        headers = [col.label for col in result.columns]
        keys = [col.key for col in result.columns]

        table_data = [headers]
        for row in result.rows:
            table_data.append([
                f"{row[k]:,.2f}" if isinstance(row.get(k), float) else str(row.get(k, ""))
                for k in keys
            ])

        col_count = len(headers)
        available_width = (page_size[0] - 3 * cm)
        col_width = available_width / col_count

        table = Table(table_data, colWidths=[col_width] * col_count, repeatRows=1)

        row_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4fa")]),
        ]
        table.setStyle(TableStyle(row_styles))
        elements.append(table)
    else:
        elements.append(Paragraph("No data found for this report.", styles["Normal"]))

    elements.append(Spacer(1, 0.5 * cm))
    elements.append(
        Paragraph(
            f"Generated by CLAUSE CLM &mdash; {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            footer_style,
        )
    )

    doc.build(elements)
    return buf.getvalue()


async def export_report(definition: ReportDefinition, fmt: str = "csv", title: str = "CLAUSE Report") -> dict:
    """Run a report and return the data in the requested export format."""
    result = await run_report(definition)

    if fmt == "json":
        return {
            "format": "json",
            "data": result.model_dump(),
        }

    if fmt == "pdf":
        pdf_bytes = _build_pdf(result, title=title)
        filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        return {
            "format": "pdf",
            "filename": filename,
            "content": pdf_bytes,
            "rows": len(result.rows),
        }

    # CSV export
    output = io.StringIO()
    if result.rows:
        writer = csv.DictWriter(output, fieldnames=result.rows[0].keys())
        writer.writeheader()
        for row in result.rows:
            writer.writerow(row)

    return {
        "format": "csv",
        "filename": f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
        "content": output.getvalue(),
        "rows": len(result.rows),
    }


# ── Saved Report CRUD ─────────────────────────────────────────────────────

async def save_report(report: ReportCreate, user_id: str) -> dict:
    """Save a named report definition to the database."""
    doc = {
        "name": report.name,
        "description": report.description,
        "definition": report.definition.model_dump(),
        "is_shared": report.is_shared,
        "created_by": user_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = reports_collection.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return doc


async def get_saved_reports(user_id: str, is_admin: bool = False) -> list[dict]:
    """List all saved reports visible to the user."""
    if is_admin:
        query = {}  # admins see all
    else:
        query = {"$or": [{"created_by": user_id}, {"is_shared": True}]}

    reports = list(
        reports_collection.find(query).sort("updated_at", -1).limit(100)
    )
    for r in reports:
        r["id"] = str(r["_id"])
        del r["_id"]
    return reports


async def get_saved_report(report_id: str, user_id: str, is_admin: bool = False) -> Optional[dict]:
    """Get a single saved report by ID."""
    if not ObjectId.is_valid(report_id):
        return None

    report = reports_collection.find_one({"_id": ObjectId(report_id)})
    if not report:
        return None

    # Check access
    if not is_admin and report.get("created_by") != user_id and not report.get("is_shared"):
        return None

    report["id"] = str(report["_id"])
    del report["_id"]
    return report


async def update_saved_report(
    report_id: str, update: ReportUpdate, user_id: str, is_admin: bool = False
) -> Optional[dict]:
    """Update a saved report definition."""
    if not ObjectId.is_valid(report_id):
        return None

    existing = reports_collection.find_one({"_id": ObjectId(report_id)})
    if not existing:
        return None
    if not is_admin and existing.get("created_by") != user_id:
        return None

    update_dict = update.model_dump(exclude_unset=True)
    if "definition" in update_dict and update_dict["definition"] is not None:
        # Already a dict from model_dump
        pass
    update_dict["updated_at"] = datetime.utcnow()

    reports_collection.update_one(
        {"_id": ObjectId(report_id)},
        {"$set": update_dict},
    )

    return await get_saved_report(report_id, user_id, is_admin)


async def delete_saved_report(report_id: str, user_id: str, is_admin: bool = False) -> bool:
    """Delete a saved report."""
    if not ObjectId.is_valid(report_id):
        return False

    query = {"_id": ObjectId(report_id)}
    if not is_admin:
        query["created_by"] = user_id

    result = reports_collection.delete_one(query)
    return result.deleted_count > 0


# ── Report Presets ────────────────────────────────────────────────────────

def get_report_presets() -> list[dict]:
    """Return pre-built report templates admins can use as starting points."""
    return [
        {
            "id": "preset_portfolio_overview",
            "name": "Contract Portfolio Overview",
            "description": "Total contracts and value grouped by contract type",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.contract_type],
                measures=[ReportMeasure.count, ReportMeasure.total_value],
                chart_type=ReportChartType.bar,
            ).model_dump(),
        },
        {
            "id": "preset_status_distribution",
            "name": "Status Distribution",
            "description": "Number of contracts by current status",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.status],
                measures=[ReportMeasure.count],
                chart_type=ReportChartType.pie,
            ).model_dump(),
        },
        {
            "id": "preset_monthly_creation",
            "name": "Monthly Creation Trend",
            "description": "Contracts created per month over the last 12 months",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.month],
                measures=[ReportMeasure.count],
                chart_type=ReportChartType.line,
                sort_by="month",
                sort_order="asc",
            ).model_dump(),
        },
        {
            "id": "preset_risk_summary",
            "name": "Risk Assessment Summary",
            "description": "Contract count and average risk score by risk level",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.risk_level],
                measures=[ReportMeasure.count, ReportMeasure.avg_risk_score],
                chart_type=ReportChartType.bar,
                filters=ReportFilter(has_ai_analysis=True),
            ).model_dump(),
        },
        {
            "id": "preset_high_value",
            "name": "High-Value Contracts",
            "description": "Contracts with value above $50,000",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.contract_type, ReportDimension.status],
                measures=[ReportMeasure.count, ReportMeasure.total_value, ReportMeasure.avg_value],
                filters=ReportFilter(value_min=50000),
                chart_type=ReportChartType.table,
            ).model_dump(),
        },
        {
            "id": "preset_expiring_90days",
            "name": "Expiring Contracts (90 Days)",
            "description": "Active contracts expiring within 90 days",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.contract_type],
                measures=[ReportMeasure.count, ReportMeasure.total_value],
                filters=ReportFilter(
                    statuses=["active"],
                    end_date_from=datetime.utcnow(),
                    end_date_to=datetime.utcnow() + timedelta(days=90),
                ),
                chart_type=ReportChartType.bar,
            ).model_dump(),
        },
        {
            "id": "preset_workflow_bottleneck",
            "name": "Workflow Stage Bottleneck",
            "description": "How many contracts are stuck at each workflow stage",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.workflow_stage],
                measures=[ReportMeasure.count, ReportMeasure.avg_value],
                chart_type=ReportChartType.bar,
            ).model_dump(),
        },
        {
            "id": "preset_risk_outliers",
            "name": "Risk Outliers",
            "description": "Contracts with risk score above 75 — sorted by highest risk",
            "definition": ReportDefinition(
                dimensions=[],
                measures=[ReportMeasure.count, ReportMeasure.avg_risk_score],
                filters=ReportFilter(risk_score_min=75),
                chart_type=ReportChartType.table,
            ).model_dump(),
        },
        {
            "id": "preset_by_creator",
            "name": "Contracts by Creator",
            "description": "Volume and total value grouped by who created each contract",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.created_by],
                measures=[ReportMeasure.count, ReportMeasure.total_value],
                chart_type=ReportChartType.bar,
                sort_by="count",
            ).model_dump(),
        },
        {
            "id": "preset_quarterly_value",
            "name": "Quarterly Value Trend",
            "description": "Total contract value per quarter over time",
            "definition": ReportDefinition(
                dimensions=[ReportDimension.quarter],
                measures=[ReportMeasure.total_value, ReportMeasure.count],
                chart_type=ReportChartType.line,
                sort_by="quarter",
                sort_order="asc",
            ).model_dump(),
        },
    ]
