with expected as (
    select
        brand_key,
        min(brand_standardized) as brand_name,
        brand_key is null as brand_missing,
        count(*) as product_rows,
        count(*)::double / nullif(sum(count(*)) over (), 0) as share_of_catalog_rows
    from {{ ref('int_product_catalog') }}
    group by brand_key
)

select
    expected.brand_key as expected_brand_key,
    actual.brand_key as actual_brand_key,
    expected.brand_name as expected_brand_name,
    actual.brand_name as actual_brand_name
from expected
full outer join {{ ref('mart_catalog_by_brand') }} as actual
    on expected.brand_key is not distinct from actual.brand_key
where expected.brand_key is distinct from actual.brand_key
    or expected.brand_name is distinct from actual.brand_name
    or expected.brand_missing is distinct from actual.brand_missing
    or expected.product_rows is distinct from actual.product_rows
    or expected.share_of_catalog_rows is distinct from actual.share_of_catalog_rows
