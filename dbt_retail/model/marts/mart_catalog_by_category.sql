{{ config(materialized='table') }}

with category_counts as (
    select
        category,
        count(*) as product_rows
    from {{ ref('int_product_catalog') }}
    group by category
)

select
    category,
    product_rows,
    product_rows::double / nullif(sum(product_rows) over (), 0) as share_of_catalog_rows
from category_counts
