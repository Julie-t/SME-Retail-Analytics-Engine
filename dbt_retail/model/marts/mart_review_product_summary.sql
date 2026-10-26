{{ config(materialized='table') }}

select
    product_id,
    product_name,
    count(*) as review_rows,
    count(*) filter (where valid_rating) as valid_rating_rows,
    avg(rating) filter (where valid_rating) as average_rating,
    count(*) filter (where recommendation_valid) as valid_recommendation_rows,
    count(*) filter (where is_recommended is true)::double
        / nullif(count(*) filter (where recommendation_valid), 0)
        as recommendation_rate
from {{ ref('int_review_analytics') }}
group by product_id, product_name
