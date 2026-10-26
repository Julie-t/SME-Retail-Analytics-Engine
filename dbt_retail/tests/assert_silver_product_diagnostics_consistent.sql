with expected as (
    select
        *,
        nullif(trim(brand), '') as expected_brand,
        lower(nullif(trim(brand), '')) as expected_brand_key,
        nullif(trim(product_name), '') as expected_product_name,
        lower(nullif(trim(product_name), '')) as expected_product_name_key,
        nullif(trim(ingredients_raw), '') as expected_ingredients_text
    from {{ ref('int_product_catalog') }}
)

select *
from expected
where brand_standardized is distinct from expected_brand
    or brand_key is distinct from expected_brand_key
    or brand_missing is distinct from (expected_brand is null)
    or product_name_standardized is distinct from expected_product_name
    or product_name_key is distinct from expected_product_name_key
    or product_name_missing is distinct from (expected_product_name is null)
    or ingredients_text is distinct from expected_ingredients_text
    or ingredients_text_missing is distinct from (expected_ingredients_text is null)
    or product_price_missing is distinct from (nullif(trim(price_usd_raw), '') is null)
    or product_price_invalid is distinct from (
        nullif(trim(price_usd_raw), '') is not null and price_usd is null
    )
    or product_rating_missing is distinct from (
        nullif(trim(product_rating_raw), '') is null
    )
    or product_rating_invalid is distinct from (
        nullif(trim(product_rating_raw), '') is not null and product_rating is null
    )
    or aggregate_review_count_missing is distinct from (
        nullif(trim(aggregate_review_count_raw), '') is null
    )
    or aggregate_review_count_invalid is distinct from (
        nullif(trim(aggregate_review_count_raw), '') is not null
        and aggregate_review_count is null
    )
    or loves_count_missing is distinct from (nullif(trim(loves_count_raw), '') is null)
    or loves_count_invalid is distinct from (
        nullif(trim(loves_count_raw), '') is not null and loves_count is null
    )
