"""Reusable UI components and chart builders for the Aboostos Retail Analytics Dashboard."""

from __future__ import annotations

from typing import Any
import altair as alt
import pandas as pd
import streamlit as st


def apply_custom_styles() -> None:
    """Inject modern CSS for sleek styling, KPI cards, and badges."""
    st.markdown(
        """
        <style>
        /* Main background and font adjustments */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        
        /* Metric card styling */
        .metric-card {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 18px 22px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .metric-card:hover {
            border-color: rgba(99, 102, 241, 0.4);
            transform: translateY(-2px);
        }
        .metric-label {
            font-size: 0.82rem;
            font-weight: 500;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }
        .metric-value {
            font-size: 1.85rem;
            font-weight: 700;
            color: #f8fafc;
            line-height: 1.2;
        }
        .metric-sub {
            font-size: 0.80rem;
            color: #cbd5e1;
            margin-top: 6px;
        }
        
        /* Badges */
        .badge-source {
            display: inline-block;
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.3);
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 0.75rem;
            font-family: monospace;
            font-weight: 600;
        }
        .badge-status-ready {
            display: inline-block;
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .badge-status-warning {
            display: inline-block;
            background: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        
        /* Banner callout */
        .limitation-banner {
            background: linear-gradient(90deg, rgba(245, 158, 11, 0.12) 0%, rgba(217, 119, 6, 0.08) 100%);
            border-left: 4px solid #f59e0b;
            border-radius: 0 8px 8px 0;
            padding: 14px 18px;
            margin-bottom: 22px;
            color: #e2e8f0;
            font-size: 0.88rem;
        }
        .limitation-banner strong {
            color: #fbbf24;
        }
        
        /* Assistant query drawer */
        .assistant-box {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 10px;
            padding: 16px 20px;
            margin-top: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(health_status: dict[str, Any] | None) -> None:
    """Render top branding header with live status pill."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("Aboostos Beauty Retail Analytics")
        st.caption(
            "Deterministic Catalogue & Customer Review Intelligence Platform | "
            "Backend: FastAPI + DuckDB + dbt + Polars + Groq"
        )
    with col2:
        if health_status and health_status.get("status") == "ready":
            st.markdown(
                '<div style="text-align: right; padding-top: 15px;">'
                '<span class="badge-status-ready">● Backend: Operational</span><br/>'
                f'<span style="font-size: 0.72rem; color: #94a3b8;">Gold Mart: {health_status.get("gold_table", "active")}</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="text-align: right; padding-top: 15px;">'
                '<span class="badge-status-warning">⚠️ Backend: Offline / Disconnected</span>'
                '</div>',
                unsafe_allow_html=True,
            )


def render_dataset_limitation_banner() -> None:
    """Render prominent banner explaining dataset boundaries."""
    st.markdown(
        """
        <div class="limitation-banner">
            <strong>⚠️ Demonstration Dataset Scope & Commercial Boundaries:</strong>
            This analytics engine is populated from a verified Kaggle Sephora snapshot containing 
            <strong>8,494 products</strong> and <strong>1,094,411 customer reviews</strong>. 
            It supports catalogue hierarchy, ingredient quality, rating distributions, and customer sentiment analytics. 
            It contains <strong>NO sales transactions, revenue, profit, margin, customer purchase orders, or stock-on-hand inventory</strong>. 
            Product prices represent catalogue shelf listings, not realized sales.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str | int | float, subtext: str = "") -> None:
    """Render a styled metric card."""
    formatted_val = f"{value:,}" if isinstance(value, int) else str(value)
    sub_html = f'<div class="metric-sub">{subtext}</div>' if subtext else ""
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{formatted_val}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_rating_distribution_chart(ratings_data: list[dict[str, Any]]) -> alt.Chart:
    """Create an Altair horizontal bar chart for rating distribution."""
    df = pd.DataFrame(ratings_data)
    df["rating_label"] = df["rating"].apply(lambda r: f"{int(r)} Star{'s' if int(r) > 1 else ''}")
    df["percentage"] = df["share_of_valid_ratings"].apply(lambda s: round(s * 100, 2) if s is not None else 0.0)
    
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=6, cornerRadiusBottomRight=6)
        .encode(
            x=alt.X("percentage:Q", title="Share of Valid Ratings (%)", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("rating_label:N", sort=["5 Stars", "4 Stars", "3 Stars", "2 Stars", "1 Star"], title=""),
            color=alt.Color(
                "percentage:Q",
                scale=alt.Scale(scheme="purples"),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("rating_label:N", title="Rating"),
                alt.Tooltip("review_rows:Q", title="Review Count", format=","),
                alt.Tooltip("percentage:Q", title="Share (%)", format=".2f"),
            ],
        )
        .properties(height=260)
    )
    
    text = chart.mark_text(
        align="left",
        baseline="middle",
        dx=8,
        color="#f1f5f9",
        fontWeight="bold",
    ).encode(text=alt.Text("percentage:Q", format=".1f"))
    
    return (chart + text).configure_axis(
        labelColor="#cbd5e1",
        titleColor="#cbd5e1",
        gridColor="rgba(255,255,255,0.06)",
    ).configure_view(strokeWidth=0)


def build_monthly_trends_chart(trends_data: list[dict[str, Any]]) -> alt.Chart:
    """Create an Altair multi-metric time-series chart over the 176 monthly buckets."""
    df = pd.DataFrame(trends_data)
    df["date"] = pd.to_datetime(df["month"], format="%Y-%m")
    
    base = alt.Chart(df).encode(
        x=alt.X("date:T", title="Submission Month", axis=alt.Axis(format="%Y-%m", labelAngle=-45))
    )
    
    volume_chart = base.mark_area(
        opacity=0.45,
        color="#6366f1",
        line={"color": "#6366f1", "strokeWidth": 2},
    ).encode(
        y=alt.Y("review_rows:Q", title="Monthly Review Volume"),
        tooltip=[
            alt.Tooltip("month:N", title="Month"),
            alt.Tooltip("review_rows:Q", title="Reviews", format=","),
            alt.Tooltip("average_rating:Q", title="Average Rating", format=".2f"),
            alt.Tooltip("recommendation_rate:Q", title="Rec. Rate", format=".1%"),
        ],
    ).properties(height=320)
    
    return volume_chart.configure_axis(
        labelColor="#cbd5e1",
        titleColor="#cbd5e1",
        gridColor="rgba(255,255,255,0.06)",
    ).configure_view(strokeWidth=0)


def build_category_distribution_chart(categories_data: list[dict[str, Any]]) -> alt.Chart:
    """Create an Altair horizontal bar chart for category share."""
    df = pd.DataFrame(categories_data)
    share_col = "share_of_catalog_rows" if "share_of_catalog_rows" in df.columns else "share_of_catalog"
    df["percentage"] = df[share_col].apply(lambda s: round(s * 100, 2) if s is not None else 0.0)
    
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
        .encode(
            x=alt.X("product_rows:Q", title="Product Count"),
            y=alt.Y("category:N", sort="-x", title="Primary Category"),
            color=alt.Color("percentage:Q", scale=alt.Scale(scheme="tealblues"), legend=None),
            tooltip=[
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("product_rows:Q", title="Products", format=","),
                alt.Tooltip("percentage:Q", title="Catalogue Share (%)", format=".2f"),
            ],
        )
        .properties(height=300)
    )
    
    return chart.configure_axis(
        labelColor="#cbd5e1",
        titleColor="#cbd5e1",
        gridColor="rgba(255,255,255,0.06)",
    ).configure_view(strokeWidth=0)


def build_brand_ranking_chart(brands_data: list[dict[str, Any]], top_n: int = 15) -> alt.Chart:
    """Create an Altair horizontal bar chart for top N brands by review count."""
    df = pd.DataFrame(brands_data).head(top_n)
    brand_col = "brand_name" if "brand_name" in df.columns else "brand_display"
    
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
        .encode(
            x=alt.X("review_rows:Q", title="Total Review Count"),
            y=alt.Y(f"{brand_col}:N", sort="-x", title="Brand"),
            color=alt.Color("average_rating:Q", scale=alt.Scale(scheme="plasma", domain=[3.5, 5.0]), title="Avg Rating"),
            tooltip=[
                alt.Tooltip(f"{brand_col}:N", title="Brand"),
                alt.Tooltip("review_rows:Q", title="Reviews", format=","),
                alt.Tooltip("average_rating:Q", title="Avg Rating", format=".2f"),
                alt.Tooltip("recommendation_rate:Q", title="Rec. Rate", format=".1%"),
            ],
        )
        .properties(height=top_n * 24 + 50)
    )
    
    return chart.configure_axis(
        labelColor="#cbd5e1",
        titleColor="#cbd5e1",
        gridColor="rgba(255,255,255,0.06)",
    ).configure_view(strokeWidth=0)
