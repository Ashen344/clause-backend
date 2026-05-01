"""
Report models — Pydantic schemas for the customizable reporting engine.

A report definition consists of:
  • Dimensions  — fields to group by (contract_type, status, month, …)
  • Measures    — aggregations to compute (count, total_value, avg_risk_score, …)
  • Filters     — criteria to narrow the data set
  • Chart type  — visual hint for the frontend (bar, pie, line, table, …)
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────

class ReportDimension(str, Enum):
    """Fields that a report can group by."""
    contract_type = "contract_type"
    status = "status"
    workflow_stage = "workflow_stage"
    risk_level = "risk_level"
    created_by = "created_by"
    month = "month"              # extracted from created_at
    quarter = "quarter"          # extracted from created_at
    year = "year"                # extracted from created_at
    tags = "tags"                # unwind + group


class ReportMeasure(str, Enum):
    """Aggregation functions available for reports."""
    count = "count"
    total_value = "total_value"
    avg_value = "avg_value"
    min_value = "min_value"
    max_value = "max_value"
    avg_risk_score = "avg_risk_score"
    max_risk_score = "max_risk_score"
    min_risk_score = "min_risk_score"


class ReportChartType(str, Enum):
    """Visual hint for the frontend renderer."""
    table = "table"
    bar = "bar"
    pie = "pie"
    line = "line"
    donut = "donut"
    stacked_bar = "stacked_bar"


class ReportSortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


# ── Filter ─────────────────────────────────────────────────────────────────

class ReportFilter(BaseModel):
    """Criteria for narrowing which contracts are included in the report."""
    date_from: Optional[datetime] = Field(
        default=None,
        description="Include contracts created on or after this date",
    )
    date_to: Optional[datetime] = Field(
        default=None,
        description="Include contracts created on or before this date",
    )
    end_date_from: Optional[datetime] = Field(
        default=None,
        description="Include contracts ending on or after this date",
    )
    end_date_to: Optional[datetime] = Field(
        default=None,
        description="Include contracts ending on or before this date",
    )
    contract_types: Optional[List[str]] = Field(
        default=None,
        description="Filter to these contract types (OR logic)",
    )
    statuses: Optional[List[str]] = Field(
        default=None,
        description="Filter to these statuses (OR logic)",
    )
    workflow_stages: Optional[List[str]] = Field(
        default=None,
        description="Filter to these workflow stages (OR logic)",
    )
    risk_levels: Optional[List[str]] = Field(
        default=None,
        description="Filter to these risk levels (OR logic)",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Filter to contracts containing any of these tags",
    )
    created_by: Optional[List[str]] = Field(
        default=None,
        description="Filter to contracts created by these user IDs",
    )
    value_min: Optional[float] = Field(
        default=None,
        description="Minimum contract value (inclusive)",
    )
    value_max: Optional[float] = Field(
        default=None,
        description="Maximum contract value (inclusive)",
    )
    risk_score_min: Optional[float] = Field(
        default=None,
        description="Minimum AI risk score (inclusive)",
    )
    risk_score_max: Optional[float] = Field(
        default=None,
        description="Maximum AI risk score (inclusive)",
    )
    has_ai_analysis: Optional[bool] = Field(
        default=None,
        description="If true, only contracts with AI analysis; if false, only without",
    )


# ── Report Definition ──────────────────────────────────────────────────────

class ReportDefinition(BaseModel):
    """Full specification for a customizable report."""
    dimensions: List[ReportDimension] = Field(
        default=[],
        description="Fields to group by (up to 3)",
    )
    measures: List[ReportMeasure] = Field(
        default=[ReportMeasure.count],
        description="Aggregations to compute",
    )
    filters: Optional[ReportFilter] = Field(
        default=None,
        description="Filter criteria",
    )
    chart_type: ReportChartType = Field(
        default=ReportChartType.table,
        description="Suggested chart type for the frontend",
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Column to sort results by (e.g. 'count', 'total_value')",
    )
    sort_order: ReportSortOrder = Field(
        default=ReportSortOrder.desc,
        description="Sort direction",
    )
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description="Max rows to return",
    )


class ReportCreate(BaseModel):
    """Schema for saving a named report definition."""
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    definition: ReportDefinition
    is_shared: bool = Field(
        default=False,
        description="If true, visible to all users; otherwise only to the creator",
    )


class ReportUpdate(BaseModel):
    """Schema for updating a saved report."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    definition: Optional[ReportDefinition] = None
    is_shared: Optional[bool] = None


# ── Report Results ─────────────────────────────────────────────────────────

class ReportColumn(BaseModel):
    """Describes a column in the report output."""
    key: str
    label: str
    type: str = "string"   # "string", "number", "date"


class ReportSummary(BaseModel):
    """Aggregate summary of the entire report."""
    total_rows: int
    total_contracts_matched: int
    summary_stats: dict = {}  # e.g. {"total_value": 1250000, "avg_risk_score": 42.3}


class ReportResult(BaseModel):
    """Structured report output returned to the frontend."""
    columns: List[ReportColumn]
    rows: List[dict]
    summary: ReportSummary
    chart_type: ReportChartType
    generated_at: datetime


# ── Outlier & Trend Requests ───────────────────────────────────────────────

class OutlierRequest(BaseModel):
    """Find contracts where a metric is above/below a threshold."""
    field: str = Field(
        description="Field to check: 'risk_score' or 'value'",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Absolute threshold (e.g. risk_score > 75)",
    )
    std_deviations: Optional[float] = Field(
        default=None,
        description="Flag contracts N standard deviations from the mean",
    )
    filters: Optional[ReportFilter] = None
    limit: int = Field(default=50, ge=1, le=200)


class TrendRequest(BaseModel):
    """Get time-series data for trend charts."""
    measure: ReportMeasure = ReportMeasure.count
    interval: str = Field(
        default="month",
        description="Time bucket: 'month' or 'quarter'",
    )
    months: int = Field(
        default=12,
        ge=1,
        le=60,
        description="How many months of history to include",
    )
    filters: Optional[ReportFilter] = None


class ExportRequest(BaseModel):
    """Request to export a report as CSV, JSON, or PDF."""
    definition: ReportDefinition
    format: str = Field(
        default="csv",
        description="Export format: 'csv', 'json', or 'pdf'",
    )
    title: str = Field(
        default="CLAUSE Report",
        description="Report title shown in the PDF header",
        max_length=200,
    )
