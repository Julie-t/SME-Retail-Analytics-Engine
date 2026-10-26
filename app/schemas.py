"""Pydantic API response schemas."""

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Service readiness status.")
    gold_table: str = Field(description="Required Gold relation used by catalog metrics.")


class CategoryCountResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str | None = Field(description="Normalized source primary category; null means missing.")
    product_count: int = Field(ge=0, description="Products in this category.")


class CategoryCountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    category_counts: tuple[CategoryCountResponse, ...]


class CatalogCategoryMetricResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str | None
    product_rows: int = Field(ge=0)
    share_of_catalog_rows: float | None = Field(default=None, ge=0, le=1)


class CatalogCategorySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    categories: tuple[CatalogCategoryMetricResponse, ...]


class BrandCountResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    brand_key: str | None
    brand_name: str | None
    brand_missing: bool
    product_rows: int = Field(ge=0)
    share_of_catalog_rows: float | None = Field(default=None, ge=0, le=1)


class BrandCountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    brands: tuple[BrandCountResponse, ...]


class CatalogQualitySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_rows: int = Field(ge=0)
    distinct_product_ids: int = Field(ge=0)
    duplicate_product_id_rows: int = Field(ge=0)
    duplicate_product_id_groups: int = Field(ge=0)
    duplicate_brand_name_candidate_rows: int = Field(ge=0)
    missing_brand_rows: int = Field(ge=0)
    missing_product_name_rows: int = Field(ge=0)
    missing_category_rows: int = Field(ge=0)
    unmapped_category_rows: int | None = Field(default=None, ge=0)
    missing_origin_rows: int | None = Field(default=None, ge=0)
    missing_formulation_attributes_rows: int | None = Field(default=None, ge=0)
    missing_ingredient_payload_rows: int | None = Field(default=None, ge=0)
    invalid_ingredient_json_rows: int | None = Field(default=None, ge=0)
    non_array_ingredient_payload_rows: int | None = Field(default=None, ge=0)
    invalid_ingredient_entry_rows: int | None = Field(default=None, ge=0)
    missing_ingredient_text_rows: int = Field(ge=0)
    missing_product_price_rows: int = Field(ge=0)
    invalid_product_price_rows: int = Field(ge=0)
    missing_product_rating_rows: int = Field(ge=0)
    invalid_product_rating_rows: int = Field(ge=0)
    missing_aggregate_review_count_rows: int = Field(ge=0)
    invalid_aggregate_review_count_rows: int = Field(ge=0)
    missing_loves_count_rows: int = Field(ge=0)
    invalid_loves_count_rows: int = Field(ge=0)
    rows_with_any_quality_issue: int = Field(ge=0)
    missing_brand_rate: float | None = Field(default=None, ge=0, le=1)
    missing_product_name_rate: float | None = Field(default=None, ge=0, le=1)
    missing_category_rate: float | None = Field(default=None, ge=0, le=1)
    unmapped_category_rate: float | None = Field(default=None, ge=0, le=1)
    missing_origin_rate: float | None = Field(default=None, ge=0, le=1)
    missing_formulation_attributes_rate: float | None = Field(default=None, ge=0, le=1)
    missing_ingredient_payload_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_ingredient_json_rate: float | None = Field(default=None, ge=0, le=1)
    non_array_ingredient_payload_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_ingredient_entry_rate: float | None = Field(default=None, ge=0, le=1)
    missing_ingredient_text_rate: float | None = Field(default=None, ge=0, le=1)
    missing_product_price_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_product_price_rate: float | None = Field(default=None, ge=0, le=1)
    missing_product_rating_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_product_rating_rate: float | None = Field(default=None, ge=0, le=1)
    missing_aggregate_review_count_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_aggregate_review_count_rate: float | None = Field(default=None, ge=0, le=1)
    missing_loves_count_rate: float | None = Field(default=None, ge=0, le=1)
    invalid_loves_count_rate: float | None = Field(default=None, ge=0, le=1)
    rows_with_any_quality_issue_rate: float | None = Field(default=None, ge=0, le=1)


class CatalogMetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_products: int = Field(ge=0)
    products_without_id: int = Field(ge=0)
    products_missing_category: int = Field(ge=0)
    products_with_unmapped_category: int | None = Field(default=None, ge=0)
    duplicate_product_id_rows: int = Field(ge=0)
    duplicate_brand_name_candidate_rows: int = Field(ge=0)
    products_missing_ingredient_text: int = Field(ge=0)
    invalid_ingredient_payload_rows: int | None = Field(default=None, ge=0)
    products_with_invalid_price: int = Field(ge=0)
    products_with_invalid_rating: int = Field(ge=0)
    products_with_invalid_aggregate_review_count: int = Field(ge=0)
    products_with_invalid_loves_count: int = Field(ge=0)
    category_counts: tuple[CategoryCountResponse, ...]


class ReviewMetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_review_rows: int = Field(ge=0)
    distinct_product_ids: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    invalid_rating_rows: int = Field(ge=0)
    average_rating: float | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Mean over valid_rating_rows; null when no 1-to-5 ratings exist.",
    )
    median_rating: float | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Median over valid_rating_rows; null when no 1-to-5 ratings exist.",
    )
    missing_product_id_rows: int = Field(ge=0)
    missing_rating_rows: int = Field(ge=0)
    missing_recommendation_rows: int = Field(ge=0)
    invalid_recommendation_rows: int = Field(ge=0)
    missing_submission_time_rows: int = Field(ge=0)
    missing_review_text_rows: int = Field(ge=0)
    missing_review_title_rows: int = Field(ge=0)
    duplicate_review_candidate_rows: int = Field(ge=0)
    orphan_product_id_rows: int = Field(ge=0)
    recommended_review_rows: int = Field(ge=0)
    not_recommended_review_rows: int = Field(ge=0)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)
    helpfulness_review_rows: int = Field(
        ge=0,
        description="Review rows with at least one internally consistent feedback vote.",
    )
    total_feedback_votes: int = Field(
        ge=0,
        description="Total positive plus negative feedback votes over valid count rows.",
    )
    positive_feedback_votes: int = Field(
        ge=0,
        description="Positive feedback vote numerator for weighted_helpfulness_rate.",
    )
    negative_feedback_votes: int = Field(
        ge=0,
        description="Negative feedback votes over valid count rows.",
    )
    helpfulness_missing_rows: int = Field(ge=0)
    helpfulness_invalid_rows: int = Field(ge=0)
    invalid_feedback_count_rows: int = Field(ge=0)
    average_helpfulness: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Unweighted mean source ratio over rows with valid feedback votes.",
    )
    weighted_helpfulness_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Positive feedback votes divided by total_feedback_votes.",
    )
    rows_with_quality_issue: int = Field(ge=0)
    rows_with_quality_issue_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewRatingBucketResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    rating: float = Field(ge=1, le=5)
    review_rows: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    share_of_valid_ratings: float | None = Field(default=None, ge=0, le=1)


class ReviewRatingDistributionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ratings: tuple[ReviewRatingBucketResponse, ...]


class ReviewRecommendationSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommended_review_rows: int = Field(ge=0)
    not_recommended_review_rows: int = Field(ge=0)
    missing_recommendation_rows: int = Field(ge=0)
    invalid_recommendation_rows: int = Field(ge=0)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    month: str
    review_rows: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    average_rating: float | None = Field(default=None, ge=1, le=5)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewTrendsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    trends: tuple[ReviewTrendResponse, ...]


class ReviewProductSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str | None
    product_name: str | None
    review_rows: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    average_rating: float | None = Field(default=None, ge=1, le=5)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewProductsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    products: tuple[ReviewProductSummaryResponse, ...]


class ReviewBrandSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    brand_key: str | None
    brand_name: str | None
    review_rows: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    average_rating: float | None = Field(default=None, ge=1, le=5)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewBrandsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    brands: tuple[ReviewBrandSummaryResponse, ...]


class ReviewCategorySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str | None
    review_rows: int = Field(ge=0)
    valid_rating_rows: int = Field(ge=0)
    average_rating: float | None = Field(default=None, ge=1, le=5)
    valid_recommendation_rows: int = Field(ge=0)
    recommendation_rate: float | None = Field(default=None, ge=0, le=1)


class ReviewCategoriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    categories: tuple[ReviewCategorySummaryResponse, ...]


class ReviewQualitySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_review_rows: int = Field(ge=0)
    missing_product_id_rows: int = Field(ge=0)
    missing_rating_rows: int = Field(ge=0)
    invalid_rating_rows: int = Field(ge=0)
    missing_recommendation_rows: int = Field(ge=0)
    invalid_recommendation_rows: int = Field(ge=0)
    missing_submission_time_rows: int = Field(ge=0)
    missing_review_text_rows: int = Field(ge=0)
    missing_review_title_rows: int = Field(ge=0)
    duplicate_review_candidate_rows: int = Field(ge=0)
    orphan_product_id_rows: int = Field(ge=0)
    helpfulness_missing_rows: int = Field(ge=0)
    helpfulness_invalid_rows: int = Field(ge=0)
    invalid_feedback_count_rows: int = Field(ge=0)
    rows_with_quality_issue: int = Field(ge=0)
    rows_with_quality_issue_rate: float | None = Field(default=None, ge=0, le=1)


class AssistantAskRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(..., min_length=3, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=20)


class AssistantAnswerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    operation: str | None = None
    supported: bool = True
    result: dict[str, object] | None = None
    filters: dict[str, object] | None = None
    metric_definition: str | None = None
    source_mart: str | None = None
    provider_status: str = Field(default="ok")
    reason: str | None = None
