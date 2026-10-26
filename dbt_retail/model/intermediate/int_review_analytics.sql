{{ config(materialized='table') }}

with products as (
    select
        product_id,
        product_name_standardized as product_name,
        brand_key,
        brand_standardized as brand_name,
        category
    from {{ ref('mart_product_catalog') }}
),
joined as (
    select
        reviews.*,
        products.product_name,
        products.brand_key,
        products.brand_name,
        products.category,
        reviews.product_id is not null and products.product_id is null
            as orphan_product_id
    from {{ ref('stg_raw_reviews') }} as reviews
    left join products
        on reviews.product_id = products.product_id
)
select
    *,
    rating_valid and rating is not null as valid_rating,
    is_recommended is not null as recommendation_valid,
    rating_missing
        or rating_invalid
        or recommendation_missing
        or recommendation_invalid
        or submission_time_missing
        or review_text_missing
        or review_title_missing
        or not feedback_counts_valid
        or helpfulness_missing
        or helpfulness_invalid
        or duplicate_review_candidate
        or product_id is null
        or orphan_product_id as review_quality_issue
from joined
