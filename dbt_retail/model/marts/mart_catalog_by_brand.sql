{{ config(materialized='table') }}

with brand_counts as (
    select
        brand_key,
        min(brand_standardized) as brand_name,
        count(*) as product_rows
    from {{ ref('int_product_catalog') }}
    group by brand_key
)

select
    brand_key,
    brand_name,
    brand_key is null as brand_missing,
    product_rows,
    product_rows::double / nullif(sum(product_rows) over (), 0) as share_of_catalog_rows
from brand_counts
