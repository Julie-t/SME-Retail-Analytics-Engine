with source as (
    select
        cast(id as varchar) as source_product_id,
        cast(brand as varchar) as brand,
        cast(name as varchar) as product_name,
        cast(category as varchar) as source_category,
        cast(category as varchar) as primary_category,
        cast(secondary_category as varchar) as secondary_category,
        cast(tertiary_category as varchar) as tertiary_category,
        cast(image_url as varchar) as image_url,
        cast(ingredients as varchar) as ingredients_raw,
        cast(price_usd as double) as price_usd,
        cast(price_usd_raw as varchar) as price_usd_raw,
        cast(rating as double) as product_rating,
        cast(rating_raw as varchar) as product_rating_raw,
        cast(reviews as bigint) as aggregate_review_count,
        cast(reviews_raw as varchar) as aggregate_review_count_raw,
        cast(loves_count as bigint) as loves_count,
        cast(loves_count_raw as varchar) as loves_count_raw,
        cast(brand_id as varchar) as brand_id,
        cast(limited_edition as boolean) as limited_edition,
        cast("new" as boolean) as is_new,
        cast(online_only as boolean) as online_only,
        cast(out_of_stock as boolean) as out_of_stock,
        cast(sephora_exclusive as boolean) as sephora_exclusive
    from {{ source('raw', 'raw_products') }}
),
normalized as (
    select
        *,
        lower(nullif(trim(source_category), '')) as normalized_source_category,
        lower(nullif(trim(brand), '')) as normalized_brand,
        lower(nullif(trim(product_name), '')) as normalized_product_name
    from source
),
diagnosed as (
    select
        *,
        count(*) over (partition by source_product_id) as product_id_record_count,
        case
            when normalized_brand is not null
                and normalized_product_name is not null
            then count(*) over (
                partition by normalized_brand, normalized_product_name
            )
            else null
        end as brand_name_candidate_record_count
    from normalized
)

select
    source_product_id as product_id,
    source_product_id,
    brand_id,
    brand,
    product_name,
    source_category,
    normalized_source_category as category,
    normalized_source_category is null as category_missing,
    primary_category,
    secondary_category,
    tertiary_category,
    image_url,
    ingredients_raw,
    price_usd_raw,
    price_usd,
    product_rating_raw,
    product_rating,
    aggregate_review_count_raw,
    aggregate_review_count,
    loves_count_raw,
    loves_count,
    limited_edition,
    is_new,
    online_only,
    out_of_stock,
    sephora_exclusive,
    product_id_record_count,
    product_id_record_count > 1 as duplicate_product_id,
    brand_name_candidate_record_count,
    coalesce(brand_name_candidate_record_count > 1, false)
        as duplicate_brand_name_candidate
from diagnosed
