{{ config(materialized='table') }}

with normalized as (
    select
        *,
        nullif(trim(brand), '') as brand_standardized,
        lower(nullif(trim(brand), '')) as brand_key,
        nullif(trim(product_name), '') as product_name_standardized,
        lower(nullif(trim(product_name), '')) as product_name_key,
        nullif(trim(ingredients_raw), '') as ingredients_text
    from {{ ref('stg_raw_products') }}
)

select
    product_id,
    source_product_id,
    brand_id,
    brand,
    brand_standardized,
    brand_key,
    brand_standardized is null as brand_missing,
    product_name,
    product_name_standardized,
    product_name_key,
    product_name_standardized is null as product_name_missing,
    source_category,
    category,
    category_missing,
    primary_category,
    secondary_category,
    tertiary_category,
    image_url,
    ingredients_raw,
    ingredients_text,
    ingredients_text is null as ingredients_text_missing,
    price_usd_raw,
    price_usd,
    nullif(trim(price_usd_raw), '') is null as product_price_missing,
    nullif(trim(price_usd_raw), '') is not null and price_usd is null
        as product_price_invalid,
    product_rating_raw,
    product_rating,
    nullif(trim(product_rating_raw), '') is null as product_rating_missing,
    nullif(trim(product_rating_raw), '') is not null and product_rating is null
        as product_rating_invalid,
    aggregate_review_count_raw,
    aggregate_review_count,
    nullif(trim(aggregate_review_count_raw), '') is null
        as aggregate_review_count_missing,
    nullif(trim(aggregate_review_count_raw), '') is not null
        and aggregate_review_count is null as aggregate_review_count_invalid,
    loves_count_raw,
    loves_count,
    nullif(trim(loves_count_raw), '') is null as loves_count_missing,
    nullif(trim(loves_count_raw), '') is not null and loves_count is null
        as loves_count_invalid,
    limited_edition,
    is_new,
    online_only,
    out_of_stock,
    sephora_exclusive,
    product_id_record_count,
    duplicate_product_id,
    brand_name_candidate_record_count,
    duplicate_brand_name_candidate
from normalized
