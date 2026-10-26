{{ config(materialized='table') }}

select
    date_trunc('month', submission_date)::date as month,
    count(*) as review_rows,
    count(*) filter (where valid_rating) as valid_rating_rows,
    avg(rating) filter (where valid_rating) as average_rating,
    count(*) filter (where recommendation_valid) as valid_recommendation_rows,
    count(*) filter (where is_recommended is true)::double
        / nullif(count(*) filter (where recommendation_valid), 0)
        as recommendation_rate
from {{ ref('int_review_analytics') }}
where submission_date is not null
group by month
