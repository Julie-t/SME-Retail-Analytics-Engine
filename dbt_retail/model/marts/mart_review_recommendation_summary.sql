{{ config(materialized='table') }}

select
    count(*) filter (where is_recommended is true) as recommended_review_rows,
    count(*) filter (where is_recommended is false) as not_recommended_review_rows,
    count(*) filter (where recommendation_missing) as missing_recommendation_rows,
    count(*) filter (where recommendation_invalid) as invalid_recommendation_rows,
    count(*) filter (where recommendation_valid) as valid_recommendation_rows,
    count(*) filter (
        where recommendation_valid and is_recommended is true
    )::double / nullif(count(*) filter (where recommendation_valid), 0)
        as recommendation_rate
from {{ ref('int_review_analytics') }}
