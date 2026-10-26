"""Aboostos Beauty Retail Analytics - Streamlit Business Dashboard.

Demonstrates deterministic catalogue and customer-review analytics for a beauty retailer,
consuming the existing FastAPI + DuckDB + dbt + Polars + Groq backend.
"""

from __future__ import annotations

import os
import pandas as pd
import streamlit as st

from dashboard.api_client import (
    APIClientError,
    APIConnectionError,
    APIStatusError,
    RetailEngineClient,
)
from dashboard.components import (
    apply_custom_styles,
    build_brand_ranking_chart,
    build_category_distribution_chart,
    build_monthly_trends_chart,
    build_rating_distribution_chart,
    render_dataset_limitation_banner,
    render_header,
    render_metric_card,
)

# 1. Page Configuration
st.set_page_config(
    page_title="Aboostos Retail Analytics",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Apply sleek styling
apply_custom_styles()


# 2. Cached API Data Fetchers (TTL = 60s)
@st.cache_data(ttl=60)
def fetch_health(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_health()


@st.cache_data(ttl=60)
def fetch_catalog_summary(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_catalog_metrics()


@st.cache_data(ttl=60)
def fetch_catalog_categories(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_catalog_category_summary()


@st.cache_data(ttl=60)
def fetch_catalog_brands(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_catalog_brand_summary()


@st.cache_data(ttl=60)
def fetch_catalog_quality(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_catalog_quality_summary()


@st.cache_data(ttl=60)
def fetch_review_summary(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_summary()


@st.cache_data(ttl=60)
def fetch_review_ratings(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_ratings()


@st.cache_data(ttl=60)
def fetch_review_recommendations(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_recommendations()


@st.cache_data(ttl=60)
def fetch_review_trends(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_trends()


@st.cache_data(ttl=60)
def fetch_review_products(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_products()


@st.cache_data(ttl=60)
def fetch_review_brands(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_brands()


@st.cache_data(ttl=60)
def fetch_review_quality(base_url: str) -> dict:
    client = RetailEngineClient(base_url=base_url)
    return client.get_review_quality()


# 3. Sidebar Controls & Settings
with st.sidebar:
    st.markdown("### 💄 Aboostos Analytics")
    st.caption("Deterministic Retail Intelligence")
    st.divider()

    # Configurable API URL
    default_url = os.environ.get("RETAIL_ENGINE_API_URL", "http://127.0.0.1:8000")
    api_base_url = st.text_input("Backend API URL", value=default_url, help="Base URL for the FastAPI serving engine.")

    # Check live health
    health_data = None
    try:
        health_data = fetch_health(api_base_url)
        st.success(f"🟢 Connected to FastAPI ({health_data.get('gold_table', 'ready')})")
    except Exception:
        st.error("🔴 Backend Disconnected")
        st.caption("Start with: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`")

    # Refresh data button
    if st.button("🔄 Refresh Data Cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("### 🧭 Navigation")
    menu = st.radio(
        "Select View",
        [
            "📊 Executive Overview",
            "⭐ Customer Review Analytics",
            "🔍 Product Explorer",
            "🏷️ Brand Explorer",
            "🛡️ Data Quality & Governance",
            "💬 AI Retail Analyst",
            "⚠️ Dataset Boundaries & Scope",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown(
        """
        <div style="font-size: 0.75rem; color: #94a3b8; line-height: 1.4;">
            <strong>Deterministic Engine v1.0.0</strong><br/>
            Engine: DuckDB + dbt<br/>
            Serving: Polars + FastAPI<br/>
            Assistant: Groq LLM
        </div>
        """,
        unsafe_allow_html=True,
    )


# 4. Main Page Rendering
render_header(health_data)
render_dataset_limitation_banner()

# Guard: Check API connectivity before attempting to render data-heavy sections
if not health_data or health_data.get("status") != "ready":
    st.error("### ⚠️ Cannot Connect to Backend Analytics API")
    st.info(
        f"""
        The Streamlit presentation layer could not reach the FastAPI service at **`{api_base_url}`**.
        
        **How to resolve:**
        1. Open a terminal in the project directory.
        2. Start the FastAPI backend service:
           ```powershell
           .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env
           ```
        3. Click **Refresh Data Cache** in the sidebar.
        """
    )
    st.stop()


# -------------------------------------------------------------
# SECTION 1: EXECUTIVE OVERVIEW
# -------------------------------------------------------------
if menu == "📊 Executive Overview":
    st.subheader("Executive Retail Overview")
    st.write("High-level key performance indicators across product catalogue and customer sentiment.")

    try:
        cat_metrics = fetch_catalog_summary(api_base_url)
        rev_metrics = fetch_review_summary(api_base_url)
        cat_summary = fetch_catalog_categories(api_base_url)
        ratings_summary = fetch_review_ratings(api_base_url)
    except APIClientError as err:
        st.error(f"Error loading executive metrics: {err}")
        st.stop()

    # KPI Grid Row 1: Catalogue
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_metric_card("Catalogue Products", cat_metrics["total_products"], "Unique SKU inventory")
    with col2:
        render_metric_card("Product Brands", len(fetch_catalog_brands(api_base_url)["brands"]), "Active brand partnerships")
    with col3:
        render_metric_card("Primary Categories", len(cat_summary["categories"]), "Department segments")
    with col4:
        render_metric_card("Total Customer Reviews", rev_metrics["total_review_rows"], "Verified user submissions")

    st.write("")
    # KPI Grid Row 2: Customer Sentiment
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        render_metric_card("Average Rating", f"{rev_metrics['average_rating']:.2f} / 5.00 ⭐", "Mean across 1.09M valid ratings")
    with col6:
        render_metric_card("Median Rating", f"{rev_metrics['median_rating']:.1f} ⭐", "Statistical rating midpoint")
    with col7:
        render_metric_card("Recommendation Rate", f"{rev_metrics['recommendation_rate']:.1%}", f"{rev_metrics['recommended_review_rows']:,} positive recommendations")
    with col8:
        render_metric_card("Customer Feedback Votes", rev_metrics["total_feedback_votes"], f"{rev_metrics['weighted_helpfulness_rate']:.1%} positive vote share")

    st.divider()

    # Charts Row
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("#### 📦 Product Catalogue by Category")
        cat_chart = build_category_distribution_chart(cat_summary["categories"])
        st.altair_chart(cat_chart, use_container_width=True)

    with chart_col2:
        st.markdown("#### ⭐ Customer Rating Distribution")
        rating_chart = build_rating_distribution_chart(ratings_summary["ratings"])
        st.altair_chart(rating_chart, use_container_width=True)


# -------------------------------------------------------------
# SECTION 2: CUSTOMER REVIEW ANALYTICS
# -------------------------------------------------------------
elif menu == "⭐ Customer Review Analytics":
    st.subheader("Customer Review Analytics & Sentiment")
    st.write("In-depth analysis of 1,094,411 customer reviews, rating shares, monthly trajectories, and feedback engagement.")

    try:
        rev_metrics = fetch_review_summary(api_base_url)
        ratings_data = fetch_review_ratings(api_base_url)["ratings"]
        recom_data = fetch_review_recommendations(api_base_url)
        trends_data = fetch_review_trends(api_base_url)["trends"]
    except APIClientError as err:
        st.error(f"Error loading review analytics: {err}")
        st.stop()

    # Metrics Summary Row
    rcol1, rcol2, rcol3, rcol4 = st.columns(4)
    with rcol1:
        render_metric_card("Mean Review Rating", f"{rev_metrics['average_rating']:.4f}", "Exact unweighted mean")
    with rcol2:
        render_metric_card("Median Rating", f"{rev_metrics['median_rating']:.1f}", "Middle value over valid ratings")
    with rcol3:
        render_metric_card("Positive Recommendations", f"{recom_data['recommended_review_rows']:,}", f"Rate: {recom_data['recommendation_rate']:.2%}")
    with rcol4:
        render_metric_card("Helpful Review Count", f"{rev_metrics['helpfulness_review_rows']:,}", f"Total votes: {rev_metrics['total_feedback_votes']:,}")

    st.divider()

    # Rating Distribution & Recommendations
    c_left, c_right = st.columns([3, 2])
    with c_left:
        st.markdown("#### 📊 Rating Distribution (1–5 Stars)")
        st.altair_chart(build_rating_distribution_chart(ratings_data), use_container_width=True)

    with c_right:
        st.markdown("#### 🎯 Recommendation Breakdown")
        rec_df = pd.DataFrame([
            {"Status": "Recommended (True)", "Count": recom_data["recommended_review_rows"], "Share": recom_data["recommended_review_rows"] / recom_data["valid_recommendation_rows"]},
            {"Status": "Not Recommended (False)", "Count": recom_data["not_recommended_review_rows"], "Share": recom_data["not_recommended_review_rows"] / recom_data["valid_recommendation_rows"]},
            {"Status": "Missing / Unstated", "Count": recom_data["missing_recommendation_rows"], "Share": None},
        ])
        st.dataframe(
            rec_df,
            column_config={
                "Status": "Recommendation Status",
                "Count": st.column_config.NumberColumn("Review Rows", format="%d"),
                "Share": st.column_config.ProgressColumn("Valid Share", format="%.2f", min_value=0.0, max_value=1.0),
            },
            hide_index=True,
            use_container_width=True,
        )
        st.caption(f"Valid recommendation denominator: **{recom_data['valid_recommendation_rows']:,} rows** (excludes unstated/null values).")

    st.divider()

    # Longitudinal Trends
    st.markdown("#### 📈 Longitudinal Submission Trends (176 Months: 2008 – 2023)")
    st.write("Monthly submission volume and review engagement across 15 years of customer feedback.")
    st.altair_chart(build_monthly_trends_chart(trends_data), use_container_width=True)


# -------------------------------------------------------------
# SECTION 3: PRODUCT EXPLORER
# -------------------------------------------------------------
elif menu == "🔍 Product Explorer":
    st.subheader("Reviewed Product Explorer")
    st.write("Browse, search, and compare all 2,351 products with customer reviews.")

    try:
        products_data = fetch_review_products(api_base_url)["products"]
        df_prod = pd.DataFrame(products_data)
    except APIClientError as err:
        st.error(f"Error loading reviewed products: {err}")
        st.stop()

    # Filter Controls
    fcol1, fcol2 = st.columns([3, 1])
    with fcol1:
        search_query = st.text_input("🔍 Search by Product Name or SKU ID", placeholder="e.g. Lip, Mask, Cream, P420652...")
    with fcol2:
        min_reviews = st.slider("Minimum Review Count", min_value=0, max_value=5000, value=10, step=25)

    # Apply filters
    filtered_df = df_prod[df_prod["review_rows"] >= min_reviews]
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_df = filtered_df[
            filtered_df["product_name"].astype(str).str.lower().str.contains(q)
            | filtered_df["product_id"].astype(str).str.lower().str.contains(q)
        ]

    st.write(f"Showing **{len(filtered_df):,}** of **{len(df_prod):,}** reviewed products:")

    # Render table
    st.dataframe(
        filtered_df[
            [
                "product_id",
                "product_name",
                "review_rows",
                "valid_rating_rows",
                "average_rating",
                "valid_recommendation_rows",
                "recommendation_rate",
            ]
        ],
        column_config={
            "product_id": st.column_config.TextColumn("SKU ID", width="small"),
            "product_name": st.column_config.TextColumn("Product Title", width="large"),
            "review_rows": st.column_config.NumberColumn("Total Reviews", format="%d"),
            "valid_rating_rows": st.column_config.NumberColumn("Ratings Count", format="%d"),
            "average_rating": st.column_config.NumberColumn("Avg Rating", format="%.2f ⭐"),
            "valid_recommendation_rows": st.column_config.NumberColumn("Recommendations Count", format="%d"),
            "recommendation_rate": st.column_config.ProgressColumn("Rec. Rate", min_value=0.0, max_value=1.0, format="%.1f%%"),
        },
        hide_index=True,
        use_container_width=True,
    )


# -------------------------------------------------------------
# SECTION 4: BRAND EXPLORER
# -------------------------------------------------------------
elif menu == "🏷️ Brand Explorer":
    st.subheader("Brand Performance & Customer Sentiment")
    st.write("Ranked review metrics across 142 beauty and skincare brands.")

    try:
        brands_data = fetch_review_brands(api_base_url)["brands"]
        df_brands = pd.DataFrame(brands_data)
    except APIClientError as err:
        st.error(f"Error loading brand analytics: {err}")
        st.stop()

    bcol1, bcol2 = st.columns([1, 1])
    with bcol1:
        top_n = st.slider("Select Top N Brands by Volume", min_value=5, max_value=30, value=15, step=5)
        st.markdown(f"#### Top {top_n} Brands by Review Volume")
        st.altair_chart(build_brand_ranking_chart(brands_data, top_n=top_n), use_container_width=True)

    with bcol2:
        st.markdown("#### Brand Sentiment & Engagement Table")
        st.dataframe(
            df_brands[
                [
                    "brand_name",
                    "review_rows",
                    "valid_rating_rows",
                    "average_rating",
                    "valid_recommendation_rows",
                    "recommendation_rate",
                ]
            ],
            column_config={
                "brand_name": st.column_config.TextColumn("Brand"),
                "review_rows": st.column_config.NumberColumn("Total Reviews", format="%d"),
                "valid_rating_rows": st.column_config.NumberColumn("Ratings Count", format="%d"),
                "average_rating": st.column_config.NumberColumn("Avg Rating", format="%.2f ⭐"),
                "valid_recommendation_rows": st.column_config.NumberColumn("Recommendations Count", format="%d"),
                "recommendation_rate": st.column_config.ProgressColumn("Rec. Rate", min_value=0.0, max_value=1.0, format="%.1f%%"),
            },
            hide_index=True,
            use_container_width=True,
            height=top_n * 24 + 50,
        )


# -------------------------------------------------------------
# SECTION 5: DATA QUALITY & GOVERNANCE
# -------------------------------------------------------------
elif menu == "🛡️ Data Quality & Governance":
    st.subheader("Data Quality & Governance Diagnostics")
    st.write("Deterministic data audits verifying catalogue integrity, ingredient structures, and review cleanliness.")

    try:
        cat_qual = fetch_catalog_quality(api_base_url)
        rev_qual = fetch_review_quality(api_base_url)
    except APIClientError as err:
        st.error(f"Error loading data quality diagnostics: {err}")
        st.stop()

    qcol1, qcol2 = st.columns(2)

    with qcol1:
        st.markdown("#### 📦 Product Catalogue Diagnostics (`main.mart_catalog_quality_summary`)")
        st.markdown(
            f"""
            - **Total Source Products:** `{cat_qual['product_rows']:,}`
            - **Unique Product IDs:** `{cat_qual['product_rows'] - cat_qual['duplicate_product_id_rows']:,}` (0 duplicates)
            - **Duplicate Brand/Name Candidates:** `{cat_qual['duplicate_brand_name_candidate_rows']:,}` ({cat_qual['duplicate_brand_name_candidate_rows'] / cat_qual['product_rows']:.2%})
            - **Missing Ingredient Text:** `{cat_qual['missing_ingredient_text_rows']:,}` ({cat_qual['missing_ingredient_text_rate']:.2%})
            - **Missing Catalogue Category:** `{cat_qual['missing_category_rows']:,}` ({cat_qual['missing_category_rate']:.2%})
            - **Missing Product Rating:** `{cat_qual['missing_product_rating_rows']:,}` ({cat_qual['missing_product_rating_rate']:.2%})
            - **Missing Aggregate Review Count:** `{cat_qual['missing_aggregate_review_count_rows']:,}` ({cat_qual['missing_aggregate_review_count_rate']:.2%})
            - **Products with Any Flagged Issue:** `{cat_qual['rows_with_any_quality_issue']:,}` ({cat_qual['rows_with_any_quality_issue_rate']:.2%})
            """
        )
        st.info("💡 **Governance Principle:** Duplicate brand/name pairings and missing attributes are tracked as diagnostic indicators. Zero product source records were dropped.")

    with qcol2:
        st.markdown("#### ⭐ Customer Review Diagnostics (`main.mart_review_quality_summary`)")
        st.markdown(
            f"""
            - **Total Loaded Reviews:** `{rev_qual['total_review_rows']:,}`
            - **Orphan Product References:** `{rev_qual['orphan_product_id_rows']:,}` (0% — 100% referential integrity)
            - **Invalid Rating Values (<1 or >5):** `{rev_qual['invalid_rating_rows']:,}` (0% invalid)
            - **Invalid Recommendation Flags:** `{rev_qual['invalid_recommendation_rows']:,}` (0% invalid)
            - **Missing Recommendation Flags:** `{rev_qual['missing_recommendation_rows']:,}` ({rev_qual['missing_recommendation_rows'] / rev_qual['total_review_rows']:.2%})
            - **Duplicate Review Candidate Rows:** `{rev_qual['duplicate_review_candidate_rows']:,}` (Diagnostic candidates across 331 groups)
            - **Review Rows with Any Flagged Issue:** `{rev_qual['rows_with_quality_issue']:,}` ({rev_qual['rows_with_quality_issue_rate']:.2%})
            """
        )
        st.info("💡 **Provenance Tracking:** Every review record preserves source file provenance (`source_filename`). No customer reviews were removed.")


# -------------------------------------------------------------
# SECTION 6: AI RETAIL ANALYST
# -------------------------------------------------------------
elif menu == "💬 AI Retail Analyst":
    st.subheader("Aboostos AI Retail Analyst (Grounded Groq Assistant)")
    st.write(
        "Ask natural-language questions about our catalogue and customer reviews. "
        "All calculations are performed deterministically in DuckDB/Polars; the AI interprets your question and explains the verified results."
    )

    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {
                "role": "assistant",
                "content": "Hello! I am the Aboostos Retail Analytics Assistant. Ask me anything about our product catalogue, category breakdowns, customer reviews, ratings, or feedback trends.",
                "supported": True,
                "source_mart": None,
                "operation": None,
                "result": None,
            }
        ]

    # Quick Prompt Chips
    st.markdown("**Suggested Questions:**")
    q_cols = st.columns(3)
    quick_queries = [
        "Give me the overall review summary.",
        "What are the product counts by category?",
        "What is the rating distribution for reviews?",
        "What are the top brands by review volume?",
        "What are the monthly review trends?",
        "What is our total sales revenue and inventory on hand?",
    ]

    selected_quick_query = None
    for i, q_text in enumerate(quick_queries):
        col = q_cols[i % 3]
        if col.button(q_text, key=f"quick_btn_{i}", use_container_width=True):
            selected_quick_query = q_text

    # Render previous conversation
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("supported") is False:
                st.warning(f"⚠️ **Commercial Boundary Refusal:** {msg.get('reason', 'Unsupported commercial query.')}")
            elif msg.get("source_mart"):
                st.markdown(
                    f'<span class="badge-source">Mart: {msg["source_mart"]}</span> '
                    f'<span class="badge-source">Op: {msg.get("operation")}</span>',
                    unsafe_allow_html=True,
                )
                if msg.get("result"):
                    with st.expander("🔍 View Raw Deterministic Metrics"):
                        st.json(msg["result"])

    # Chat Input
    user_query = st.chat_input("Ask an analytics question...")
    if selected_quick_query:
        user_query = selected_quick_query

    if user_query:
        # Add user message
        st.session_state.chat_history.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.write(user_query)

        # Query backend assistant endpoint
        with st.chat_message("assistant"):
            with st.spinner("Analyzing request and fetching deterministic metrics..."):
                client = RetailEngineClient(base_url=api_base_url)
                try:
                    response = client.ask_assistant(user_query, max_results=10)
                    answer_text = response.get("answer", "No answer provided.")
                    supported = response.get("supported", True)
                    source_mart = response.get("source_mart")
                    operation = response.get("operation")
                    result_data = response.get("result")
                    reason = response.get("reason")

                    st.write(answer_text)
                    if not supported:
                        st.warning(f"⚠️ **Commercial Boundary Refusal:** {reason}")
                    elif source_mart:
                        st.markdown(
                            f'<span class="badge-source">Mart: {source_mart}</span> '
                            f'<span class="badge-source">Op: {operation}</span>',
                            unsafe_allow_html=True,
                        )
                        if result_data:
                            with st.expander("🔍 View Raw Deterministic Metrics"):
                                st.json(result_data)

                    # Save to session history
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": answer_text,
                            "supported": supported,
                            "source_mart": source_mart,
                            "operation": operation,
                            "result": result_data,
                            "reason": reason,
                        }
                    )
                except APIStatusError as err:
                    err_msg = f"Assistant error ({err.status_code}): {err.detail}"
                    st.error(err_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": err_msg, "supported": False})
                except APIConnectionError as err:
                    err_msg = f"Connection error: {err}"
                    st.error(err_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": err_msg, "supported": False})


# -------------------------------------------------------------
# SECTION 7: DATASET BOUNDARIES & SCOPE
# -------------------------------------------------------------
elif menu == "⚠️ Dataset Boundaries & Scope":
    st.subheader("Dataset Scope & Commercial Boundaries")
    st.write("Detailed architectural documentation of the data foundation, supported operations, and boundary limitations.")

    st.markdown(
        """
        ### 1. What This Engine Supports
        - **Product Catalogue Intelligence:** 8,494 unique SKUs across 304 brands and 9 primary categories.
        - **Catalogue Specifications:** Preserved ingredient text, listed shelf prices (`price_usd`), product ratings, and aggregate review counts.
        - **Customer Review Sentiment:** 1,094,411 individual customer reviews, ratings (1 to 5 stars), and recommendation status (84.00% positive).
        - **Community Helpfulness:** 4,571,493 feedback votes across 532,819 feedback-bearing reviews.
        - **Longitudinal Trajectories:** 15-year monthly review trends from August 2008 through March 2023 across 176 monthly buckets.
        - **Data Quality Audits:** Automated Medallion data-quality flags for missing attributes, duplicate candidates, and orphan references.

        ---

        ### 2. What This Engine Does NOT Support
        - ❌ **No Point-of-Sale Transactions:** The engine contains zero cash register or e-commerce transaction lines.
        - ❌ **No Sales Revenue or Profit:** Listed prices (`price_usd`) represent catalogue shelf attributes, not realized transaction amounts. No discounts, taxes, or gross margins can be inferred.
        - ❌ **No Inventory / Stock-on-Hand:** The dataset contains no warehouse inventory, store stock, or supply chain replenishment movements.
        - ❌ **No Customer Order History:** Review author IDs are preserved for review provenance, but contain no repeat-purchase histories or RFM segmentation.

        ---

        ### 3. Architecture Principles
        - **Zero Hallucination:** The Large Language Model (Groq) is strictly prohibited from computing mathematical calculations or running arbitrary SQL. All numbers are computed deterministically in DuckDB and Polars.
        - **Decoupled Presentation:** Streamlit interacts exclusively with FastAPI via typed HTTP JSON endpoints. No direct connection to the production DuckDB database exists from the dashboard layer.
        """
    )
