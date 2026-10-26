{{ config(materialized='table') }}

with counts as (
    select
        count(*) as product_rows,
        count(distinct product_id) as distinct_product_ids,
        count(*) filter (where duplicate_product_id) as duplicate_product_id_rows,
        count(distinct product_id) filter (
            where duplicate_product_id
        ) as duplicate_product_id_groups,
        count(*) filter (
            where duplicate_brand_name_candidate
        ) as duplicate_brand_name_candidate_rows,
        count(*) filter (where brand_missing) as missing_brand_rows,
        count(*) filter (where product_name_missing) as missing_product_name_rows,
        count(*) filter (where category_missing) as missing_category_rows,
        count(*) filter (where ingredients_text_missing)
            as missing_ingredient_text_rows,
        count(*) filter (where product_price_missing) as missing_product_price_rows,
        count(*) filter (where product_price_invalid) as invalid_product_price_rows,
        count(*) filter (where product_rating_missing) as missing_product_rating_rows,
        count(*) filter (where product_rating_invalid) as invalid_product_rating_rows,
        count(*) filter (where aggregate_review_count_missing)
            as missing_aggregate_review_count_rows,
        count(*) filter (where aggregate_review_count_invalid)
            as invalid_aggregate_review_count_rows,
        count(*) filter (where loves_count_missing) as missing_loves_count_rows,
        count(*) filter (where loves_count_invalid) as invalid_loves_count_rows,
        count(*) filter (
            where brand_missing
                or product_name_missing
                or category_missing
                or ingredients_text_missing
                or product_price_missing
                or product_price_invalid
                or product_rating_missing
                or product_rating_invalid
                or aggregate_review_count_missing
                or aggregate_review_count_invalid
                or loves_count_missing
                or loves_count_invalid
                or duplicate_product_id
                or duplicate_brand_name_candidate
        ) as rows_with_any_quality_issue
    from {{ ref('int_product_catalog') }}
)

select
    *,
    missing_brand_rows::double / nullif(product_rows, 0) as missing_brand_rate,
    missing_product_name_rows::double / nullif(product_rows, 0) as missing_product_name_rate,
    missing_category_rows::double / nullif(product_rows, 0) as missing_category_rate,
    missing_ingredient_text_rows::double
        / nullif(product_rows, 0) as missing_ingredient_text_rate,
    missing_product_price_rows::double
        / nullif(product_rows, 0) as missing_product_price_rate,
    invalid_product_price_rows::double
        / nullif(product_rows, 0) as invalid_product_price_rate,
    missing_product_rating_rows::double
        / nullif(product_rows, 0) as missing_product_rating_rate,
    invalid_product_rating_rows::double
        / nullif(product_rows, 0) as invalid_product_rating_rate,
    missing_aggregate_review_count_rows::double
        / nullif(product_rows, 0) as missing_aggregate_review_count_rate,
    invalid_aggregate_review_count_rows::double
        / nullif(product_rows, 0) as invalid_aggregate_review_count_rate,
    missing_loves_count_rows::double
        / nullif(product_rows, 0) as missing_loves_count_rate,
    invalid_loves_count_rows::double
        / nullif(product_rows, 0) as invalid_loves_count_rate,
    rows_with_any_quality_issue::double
        / nullif(product_rows, 0) as rows_with_any_quality_issue_rate
from counts
