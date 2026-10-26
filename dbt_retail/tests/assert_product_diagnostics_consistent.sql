with expected as (
    select
        *,
        lower(nullif(trim(source_category), '')) as expected_category,
        lower(nullif(trim(brand), '')) as normalized_brand,
        lower(nullif(trim(product_name), '')) as normalized_product_name,
        count(*) over (partition by product_id) as expected_product_id_record_count,
        case
            when nullif(trim(brand), '') is not null
                and nullif(trim(product_name), '') is not null
            then count(*) over (
                partition by lower(nullif(trim(brand), '')),
                             lower(nullif(trim(product_name), ''))
            )
            else null
        end as expected_brand_name_candidate_record_count
    from {{ ref('stg_raw_products') }}
)

select *
from expected
where category_missing is distinct from (expected_category is null)
   or category is distinct from expected_category
   or product_id_record_count is distinct from expected_product_id_record_count
   or duplicate_product_id is distinct from (expected_product_id_record_count > 1)
   or brand_name_candidate_record_count
        is distinct from expected_brand_name_candidate_record_count
   or duplicate_brand_name_candidate is distinct from (
        coalesce(expected_brand_name_candidate_record_count > 1, false)
   )
   or price_usd is distinct from try_cast(nullif(trim(price_usd_raw), '') as double)
   or product_rating is distinct from
        try_cast(nullif(trim(product_rating_raw), '') as double)
   or aggregate_review_count is distinct from
        try_cast(nullif(trim(aggregate_review_count_raw), '') as bigint)
   or loves_count is distinct from try_cast(nullif(trim(loves_count_raw), '') as bigint)
