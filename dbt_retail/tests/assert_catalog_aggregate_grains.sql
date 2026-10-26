select
    'category' as aggregate_name,
    cast(category as varchar) as aggregate_key,
    count(*) as duplicate_rows
from {{ ref('mart_catalog_by_category') }}
group by category
having count(*) > 1

union all

select
    'brand' as aggregate_name,
    coalesce(brand_key, '<missing>') as aggregate_key,
    count(*) as duplicate_rows
from {{ ref('mart_catalog_by_brand') }}
group by brand_key
having count(*) > 1

union all

select
    'quality_summary' as aggregate_name,
    'singleton' as aggregate_key,
    count(*) as duplicate_rows
from {{ ref('mart_catalog_quality_summary') }}
having count(*) <> 1
