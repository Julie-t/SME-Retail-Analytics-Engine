{{ config(materialized='table') }}

with counts as (
    select
        rating,
        count(*) as review_rows
    from {{ ref('int_review_analytics') }}
    where valid_rating
    group by rating
),
totals as (
    select count(*) as valid_rating_rows
    from {{ ref('int_review_analytics') }}
    where valid_rating
)
select
    counts.rating,
    counts.review_rows,
    totals.valid_rating_rows,
    counts.review_rows::double / nullif(totals.valid_rating_rows, 0)
        as share_of_valid_ratings
from counts
cross join totals
