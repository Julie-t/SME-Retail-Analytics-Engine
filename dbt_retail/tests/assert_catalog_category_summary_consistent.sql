with expected as (
    select
        category,
        count(*) as product_rows,
        count(*)::double / nullif(sum(count(*)) over (), 0) as share_of_catalog_rows
    from {{ ref('int_product_catalog') }}
    group by category
)

select
    coalesce(expected.category, actual.category) as category,
    expected.product_rows as expected_product_rows,
    actual.product_rows as actual_product_rows,
    expected.share_of_catalog_rows as expected_share,
    actual.share_of_catalog_rows as actual_share
from expected
full outer join {{ ref('mart_catalog_by_category') }} as actual
    on expected.category is not distinct from actual.category
where expected.product_rows is distinct from actual.product_rows
    or abs(
        expected.share_of_catalog_rows - actual.share_of_catalog_rows
    ) > 0.000000000001
    or expected.share_of_catalog_rows is distinct from actual.share_of_catalog_rows
