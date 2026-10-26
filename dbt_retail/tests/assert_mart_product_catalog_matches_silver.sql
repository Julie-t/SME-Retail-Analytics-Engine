with silver as (
    select *
    from {{ ref('int_product_catalog') }}
),
mart as (
    select *
    from {{ ref('mart_product_catalog') }}
)

select 'silver_row_missing_from_mart' as failure, missing.*
from (
    select * from silver
    except all
    select * from mart
) as missing

union all

select 'mart_row_not_in_silver' as failure, extra.*
from (
    select * from mart
    except all
    select * from silver
) as extra
