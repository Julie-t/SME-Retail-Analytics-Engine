{{ config(materialized='table') }}

with counts as (
    select
        count(*) as total_review_rows,
        count(*) filter (where product_id is null) as missing_product_id_rows,
        count(*) filter (where rating_missing) as missing_rating_rows,
        count(*) filter (where rating_invalid) as invalid_rating_rows,
        count(*) filter (where recommendation_missing)
            as missing_recommendation_rows,
        count(*) filter (where recommendation_invalid)
            as invalid_recommendation_rows,
        count(*) filter (where submission_time_missing)
            as missing_submission_time_rows,
        count(*) filter (where review_text_missing) as missing_review_text_rows,
        count(*) filter (where review_title_missing) as missing_review_title_rows,
        count(*) filter (where duplicate_review_candidate)
            as duplicate_review_candidate_rows,
        count(*) filter (where orphan_product_id) as orphan_product_id_rows,
        count(*) filter (where helpfulness_missing) as helpfulness_missing_rows,
        count(*) filter (where helpfulness_invalid) as helpfulness_invalid_rows,
        count(*) filter (where not feedback_counts_valid)
            as invalid_feedback_count_rows,
        count(*) filter (where review_quality_issue) as rows_with_quality_issue
    from {{ ref('int_review_analytics') }}
)
select
    *,
    rows_with_quality_issue::double / nullif(total_review_rows, 0)
        as rows_with_quality_issue_rate
from counts
