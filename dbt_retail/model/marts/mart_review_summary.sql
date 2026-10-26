{{ config(materialized='table') }}

with summary as (
    select
        count(*) as total_review_rows,
        count(distinct product_id) as distinct_product_ids,
        count(*) filter (where valid_rating) as valid_rating_rows,
        count(*) filter (where rating_invalid) as invalid_rating_rows,
        avg(rating) filter (where valid_rating) as average_rating,
        median(rating) filter (where valid_rating) as median_rating,
        count(*) filter (where product_id is null) as missing_product_id_rows,
        count(*) filter (where rating_missing) as missing_rating_rows,
        count(*) filter (where submission_time_missing) as missing_submission_time_rows,
        count(*) filter (where review_text_missing) as missing_review_text_rows,
        count(*) filter (where review_title_missing) as missing_review_title_rows,
        count(*) filter (where duplicate_review_candidate)
            as duplicate_review_candidate_rows,
        count(*) filter (where orphan_product_id) as orphan_product_id_rows,
        count(*) filter (where recommendation_missing)
            as missing_recommendation_rows,
        count(*) filter (where recommendation_invalid)
            as invalid_recommendation_rows,
        count(*) filter (where is_recommended is true)
            as recommended_review_rows,
        count(*) filter (where is_recommended is false)
            as not_recommended_review_rows,
        count(*) filter (where recommendation_valid)
            as valid_recommendation_rows,
        count(*) filter (
            where has_feedback and feedback_counts_valid
        ) as helpfulness_review_rows,
        coalesce(sum(total_feedback_count) filter (where feedback_counts_valid), 0)
            as total_feedback_votes,
        coalesce(sum(positive_feedback_count) filter (where feedback_counts_valid), 0)
            as positive_feedback_votes,
        coalesce(sum(negative_feedback_count) filter (where feedback_counts_valid), 0)
            as negative_feedback_votes,
        count(*) filter (where helpfulness_missing) as helpfulness_missing_rows,
        count(*) filter (where helpfulness_invalid) as helpfulness_invalid_rows,
        count(*) filter (where not feedback_counts_valid)
            as invalid_feedback_count_rows,
        avg(helpfulness) filter (where helpfulness_valid and has_feedback)
            as average_helpfulness,
        coalesce(sum(positive_feedback_count) filter (
            where feedback_counts_valid
        ), 0)::double
            / nullif(coalesce(sum(total_feedback_count) filter (
                where feedback_counts_valid
            ), 0), 0) as weighted_helpfulness_rate,
        count(*) filter (where review_quality_issue) as rows_with_quality_issue
    from {{ ref('int_review_analytics') }}
)
select
    *,
    recommended_review_rows::double
        / nullif(valid_recommendation_rows, 0) as recommendation_rate,
    rows_with_quality_issue::double / nullif(total_review_rows, 0)
        as rows_with_quality_issue_rate
from summary
