with source as (
    select
        source_filename,
        nullif(trim(product_id), '') as product_id,
        nullif(trim(rating), '') as rating_raw,
        try_cast(nullif(trim(rating), '') as double) as rating,
        nullif(trim(is_recommended), '') as recommendation_raw,
        nullif(trim(submission_time), '') as submission_time_raw,
        try_cast(nullif(trim(submission_time), '') as date) as submission_date,
        nullif(trim(helpfulness), '') as helpfulness_raw,
        try_cast(nullif(trim(helpfulness), '') as double) as helpfulness,
        try_cast(nullif(trim(total_feedback_count), '') as bigint)
            as total_feedback_count,
        try_cast(nullif(trim(total_pos_feedback_count), '') as bigint)
            as positive_feedback_count,
        try_cast(nullif(trim(total_neg_feedback_count), '') as bigint)
            as negative_feedback_count,
        nullif(trim(review_text), '') as review_text,
        nullif(trim(review_title), '') as review_title,
        author_id
    from {{ source('raw', 'sephora_reviews') }}
),
parsed as (
    select
        *,
        case
            when recommendation_raw is null then null
            when try_cast(recommendation_raw as double) in (0, 1)
                then try_cast(recommendation_raw as double) = 1
            else try_cast(recommendation_raw as boolean)
        end as is_recommended
    from source
),
diagnosed as (
    select
        *,
        total_feedback_count is not null
            and positive_feedback_count is not null
            and negative_feedback_count is not null
            and total_feedback_count >= 0
            and positive_feedback_count >= 0
            and negative_feedback_count >= 0
            and total_feedback_count = positive_feedback_count + negative_feedback_count
            as feedback_counts_valid,
        case
            when total_feedback_count > 0 then
                feedback_counts_valid
                and helpfulness is not null
                and helpfulness between 0 and 1
                and abs(
                    helpfulness
                    - positive_feedback_count::double / total_feedback_count
                ) <= 0.000001
            else helpfulness is null
        end as helpfulness_valid,
        count(*) over (
            partition by
                product_id,
                author_id,
                rating_raw,
                recommendation_raw,
                submission_time_raw,
                review_text,
                review_title
        ) as duplicate_review_candidate_count
    from parsed
)
select
    source_filename,
    product_id,
    rating_raw,
    rating,
    rating is not null and rating between 1 and 5 as rating_valid,
    rating_raw is null as rating_missing,
    rating_raw is not null and (
        rating is null or rating < 1 or rating > 5
    ) as rating_invalid,
    recommendation_raw is null as recommendation_missing,
    recommendation_raw is not null and is_recommended is null
        as recommendation_invalid,
    is_recommended,
    helpfulness_raw,
    helpfulness,
    total_feedback_count,
    positive_feedback_count,
    negative_feedback_count,
    coalesce(total_feedback_count > 0, false) as has_feedback,
    feedback_counts_valid,
    helpfulness_valid,
    coalesce(total_feedback_count > 0 and helpfulness is null, false)
        as helpfulness_missing,
    coalesce(
        helpfulness_raw is not null and helpfulness is null
        or helpfulness is not null and not helpfulness_valid,
        false
    ) as helpfulness_invalid,
    submission_time_raw,
    submission_date,
    submission_time_raw is null or submission_date is null
        as submission_time_missing,
    review_text,
    review_text is null as review_text_missing,
    review_title,
    review_title is null as review_title_missing,
    duplicate_review_candidate_count > 1 as duplicate_review_candidate
from diagnosed
