from types import SimpleNamespace

from app.models import Product
from app.services.scoring_service import ScoringService


def make_product(**kwargs):
    defaults = {
        "current_price": 3000,
        "avg_price_90": 3100,
        "lowest_price_90": 2900,
        "highest_price_90": 3300,
        "sales_rank_drops_90": 24,
        "new_offer_count": 7,
        "amazon_in_stock": False,
        "amazon_was_in_stock_90": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_sales_score_thresholds():
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=None)) == 0
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=3)) == 0
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=4)) == 10
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=10)) == 25
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=20)) == 35
    assert ScoringService.calculate_sales_score(SimpleNamespace(sales_rank_drops_90=50)) == 40


def test_price_stability_score_missing_or_invalid_data_returns_zero():
    missing = SimpleNamespace(
        current_price=1000,
        avg_price_90=None,
        lowest_price_90=900,
        highest_price_90=1100,
    )
    zero_avg = SimpleNamespace(
        current_price=1000,
        avg_price_90=0,
        lowest_price_90=900,
        highest_price_90=1100,
    )

    assert ScoringService.calculate_price_stability_score(missing) == 0
    assert ScoringService.calculate_price_stability_score(zero_avg) == 0


def test_price_stability_score_thresholds():
    best = SimpleNamespace(
        current_price=950,
        avg_price_90=1000,
        lowest_price_90=900,
        highest_price_90=1100,
    )
    medium = SimpleNamespace(
        current_price=920,
        avg_price_90=1000,
        lowest_price_90=700,
        highest_price_90=1200,
    )
    low = SimpleNamespace(
        current_price=850,
        avg_price_90=1000,
        lowest_price_90=700,
        highest_price_90=1200,
    )
    bad = SimpleNamespace(
        current_price=700,
        avg_price_90=1000,
        lowest_price_90=650,
        highest_price_90=1200,
    )

    assert ScoringService.calculate_price_stability_score(best) == 25
    assert ScoringService.calculate_price_stability_score(medium) == 18
    assert ScoringService.calculate_price_stability_score(low) == 10
    assert ScoringService.calculate_price_stability_score(bad) == 0


def test_competition_score_thresholds():
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=1)) == 5
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=2)) == 15
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=3)) == 25
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=10)) == 25
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=11)) == 20
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=16)) == 10
    assert ScoringService.calculate_competition_score(SimpleNamespace(new_offer_count=31)) == 0


def test_risk_score_rules():
    none_amazon = SimpleNamespace(amazon_in_stock=False, amazon_was_in_stock_90=False)
    past_only_amazon = SimpleNamespace(amazon_in_stock=False, amazon_was_in_stock_90=True)
    current_amazon = SimpleNamespace(amazon_in_stock=True, amazon_was_in_stock_90=True)

    assert ScoringService.calculate_risk_score(none_amazon) == 10
    assert ScoringService.calculate_risk_score(past_only_amazon) == 5
    assert ScoringService.calculate_risk_score(current_amazon) == 0


def test_keepa_score_is_sum_of_component_scores():
    product = SimpleNamespace(
        sales_rank_drops_90=20,
        current_price=950,
        avg_price_90=1000,
        lowest_price_90=900,
        highest_price_90=1100,
        new_offer_count=3,
        amazon_in_stock=False,
        amazon_was_in_stock_90=False,
    )

    assert ScoringService.calculate_sales_score(product) == 35
    assert ScoringService.calculate_price_stability_score(product) == 25
    assert ScoringService.calculate_competition_score(product) == 25
    assert ScoringService.calculate_risk_score(product) == 10
    assert ScoringService.calculate_keepa_score(product) == 95


def test_invalid_string_values_do_not_raise():
    product = SimpleNamespace(
        sales_rank_drops_90="invalid",
        current_price="invalid",
        avg_price_90="invalid",
        lowest_price_90="invalid",
        highest_price_90="invalid",
        new_offer_count="invalid",
        amazon_in_stock="invalid",
        amazon_was_in_stock_90="invalid",
    )

    assert ScoringService.calculate_sales_score(product) == 0
    assert ScoringService.calculate_price_stability_score(product) == 0
    assert ScoringService.calculate_competition_score(product) == 0
    assert ScoringService.calculate_risk_score(product) == 0
    assert ScoringService.calculate_keepa_score(product) == 0


def test_judge_product_returns_unknown_when_required_data_missing():
    product = make_product(current_price=None)
    assert ScoringService.judge_product(product) == Product.JUDGEMENT_UNKNOWN


def test_judge_product_returns_good_when_score_is_80_or_more():
    product = make_product(
        sales_rank_drops_90=20,
        current_price=950,
        avg_price_90=1000,
        lowest_price_90=900,
        highest_price_90=1100,
        new_offer_count=3,
        amazon_in_stock=False,
        amazon_was_in_stock_90=False,
    )
    assert ScoringService.calculate_keepa_score(product) >= 80
    assert ScoringService.judge_product(product) == Product.JUDGEMENT_GOOD


def test_judge_product_returns_watch_when_score_is_60_to_79():
    product = make_product(
        sales_rank_drops_90=10,
        current_price=920,
        avg_price_90=1000,
        lowest_price_90=700,
        highest_price_90=1200,
        new_offer_count=2,
        amazon_in_stock=False,
        amazon_was_in_stock_90=True,
    )
    score = ScoringService.calculate_keepa_score(product)
    assert 60 <= score <= 79
    assert ScoringService.judge_product(product) == Product.JUDGEMENT_WATCH


def test_judge_product_returns_bad_when_score_is_59_or_less():
    product = make_product(
        sales_rank_drops_90=4,
        current_price=700,
        avg_price_90=1000,
        lowest_price_90=650,
        highest_price_90=1200,
        new_offer_count=31,
        amazon_in_stock=True,
        amazon_was_in_stock_90=True,
    )
    score = ScoringService.calculate_keepa_score(product)
    assert score <= 59
    assert ScoringService.judge_product(product) == Product.JUDGEMENT_BAD


def test_build_judgement_reasons_returns_string_list():
    reasons = ScoringService.build_judgement_reasons(make_product())
    assert isinstance(reasons, list)
    assert reasons
    assert all(isinstance(reason, str) for reason in reasons)


def test_build_judgement_reasons_handles_missing_data_without_exception():
    reasons = ScoringService.build_judgement_reasons(make_product(sales_rank_drops_90=None))
    assert isinstance(reasons, list)
    assert reasons


def test_build_judgement_reasons_contains_sales_data_missing_reason():
    reasons = ScoringService.build_judgement_reasons(make_product(sales_rank_drops_90=None))
    assert any("ランキング変動データが不足" in reason for reason in reasons)


def test_build_judgement_reasons_contains_sales_positive_reason():
    reasons = ScoringService.build_judgement_reasons(make_product(sales_rank_drops_90=24))
    assert any("90日ランキング変動が24回" in reason for reason in reasons)


def test_build_judgement_reasons_contains_competition_warning_when_many_offers():
    reasons = ScoringService.build_judgement_reasons(make_product(new_offer_count=31))
    assert any("値下げ競争" in reason for reason in reasons)


def test_build_judgement_reasons_contains_amazon_in_stock_warning():
    reasons = ScoringService.build_judgement_reasons(make_product(amazon_in_stock=True))
    assert any("Amazon本体が現在在庫" in reason for reason in reasons)


def test_build_judgement_reasons_contains_total_score_and_judgement():
    reasons = ScoringService.build_judgement_reasons(make_product())
    assert any("総合Keepaスコア" in reason and "判定は" in reason for reason in reasons)


def test_default_status_for_judgement_mapping():
    assert (
        ScoringService.default_status_for_judgement(Product.JUDGEMENT_GOOD)
        == Product.STATUS_CANDIDATE
    )
    assert (
        ScoringService.default_status_for_judgement(Product.JUDGEMENT_WATCH)
        == Product.STATUS_UNREVIEWED
    )
    assert (
        ScoringService.default_status_for_judgement(Product.JUDGEMENT_BAD)
        == Product.STATUS_EXCLUDED
    )
    assert (
        ScoringService.default_status_for_judgement(Product.JUDGEMENT_UNKNOWN)
        == Product.STATUS_HOLD
    )
    assert (
        ScoringService.default_status_for_judgement("not-known")
        == Product.STATUS_HOLD
    )


def test_apply_scoring_sets_all_score_fields_and_returns_same_product():
    product = make_product(
        sales_score=None,
        price_stability_score=None,
        competition_score=None,
        risk_score=None,
        keepa_score=None,
        judgement=None,
        status=None,
    )

    returned = ScoringService.apply_scoring(product)

    assert returned is product
    assert product.sales_score is not None
    assert product.price_stability_score is not None
    assert product.competition_score is not None
    assert product.risk_score is not None
    assert product.keepa_score is not None
    assert product.judgement in Product.VALID_JUDGEMENTS
    assert product.status in Product.VALID_STATUSES
    assert product.keepa_score == (
        product.sales_score
        + product.price_stability_score
        + product.competition_score
        + product.risk_score
    )


def test_apply_scoring_status_mapping_good_watch_bad_unknown():
    good_product = make_product(
        sales_rank_drops_90=20,
        current_price=950,
        avg_price_90=1000,
        lowest_price_90=900,
        highest_price_90=1100,
        new_offer_count=3,
        amazon_in_stock=False,
        amazon_was_in_stock_90=False,
    )
    ScoringService.apply_scoring(good_product)
    assert good_product.judgement == Product.JUDGEMENT_GOOD
    assert good_product.status == Product.STATUS_CANDIDATE

    watch_product = make_product(
        sales_rank_drops_90=10,
        current_price=920,
        avg_price_90=1000,
        lowest_price_90=700,
        highest_price_90=1200,
        new_offer_count=2,
        amazon_in_stock=False,
        amazon_was_in_stock_90=True,
    )
    ScoringService.apply_scoring(watch_product)
    assert watch_product.judgement == Product.JUDGEMENT_WATCH
    assert watch_product.status == Product.STATUS_UNREVIEWED

    bad_product = make_product(
        sales_rank_drops_90=4,
        current_price=700,
        avg_price_90=1000,
        lowest_price_90=650,
        highest_price_90=1200,
        new_offer_count=31,
        amazon_in_stock=True,
        amazon_was_in_stock_90=True,
    )
    ScoringService.apply_scoring(bad_product)
    assert bad_product.judgement == Product.JUDGEMENT_BAD
    assert bad_product.status == Product.STATUS_EXCLUDED

    unknown_product = make_product(current_price=None)
    ScoringService.apply_scoring(unknown_product)
    assert unknown_product.judgement == Product.JUDGEMENT_UNKNOWN
    assert unknown_product.status == Product.STATUS_HOLD


def test_apply_scoring_handles_invalid_values_without_exception():
    product = make_product(
        current_price="invalid",
        avg_price_90="invalid",
        lowest_price_90="invalid",
        highest_price_90="invalid",
        sales_rank_drops_90="invalid",
        new_offer_count="invalid",
        amazon_in_stock="invalid",
        amazon_was_in_stock_90="invalid",
        sales_score=None,
        price_stability_score=None,
        competition_score=None,
        risk_score=None,
        keepa_score=None,
        judgement=None,
        status=None,
    )

    returned = ScoringService.apply_scoring(product)

    assert returned is product
    assert isinstance(product.sales_score, int)
    assert isinstance(product.price_stability_score, int)
    assert isinstance(product.competition_score, int)
    assert isinstance(product.risk_score, int)
    assert isinstance(product.keepa_score, int)
    assert product.judgement in Product.VALID_JUDGEMENTS
    assert product.status in Product.VALID_STATUSES
