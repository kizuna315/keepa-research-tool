import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AppSetting, Product, ProductResearchRun, ResearchRun


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def test_research_run_valid_statuses_are_defined():
    assert {
        ResearchRun.STATUS_PENDING,
        ResearchRun.STATUS_RUNNING,
        ResearchRun.STATUS_COMPLETED,
        ResearchRun.STATUS_FAILED,
        ResearchRun.STATUS_CANCELLED,
    }.issubset(ResearchRun.VALID_STATUSES)


def test_product_valid_judgements_are_defined():
    assert {
        Product.JUDGEMENT_GOOD,
        Product.JUDGEMENT_WATCH,
        Product.JUDGEMENT_BAD,
        Product.JUDGEMENT_UNKNOWN,
    }.issubset(Product.VALID_JUDGEMENTS)


def test_product_valid_statuses_are_defined():
    assert {
        Product.STATUS_UNREVIEWED,
        Product.STATUS_CANDIDATE,
        Product.STATUS_HOLD,
        Product.STATUS_EXCLUDED,
        Product.STATUS_SUPPLIER_SEARCH_PENDING,
    }.issubset(Product.VALID_STATUSES)


def test_app_setting_known_keys_are_defined():
    assert {
        AppSetting.KEY_KEEPA_API_KEY,
        AppSetting.KEY_DEFAULT_DOMAIN_ID,
        AppSetting.KEY_DEFAULT_MIN_PRICE,
        AppSetting.KEY_DEFAULT_MAX_PRICE,
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT,
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT,
        AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK,
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90,
        AppSetting.KEY_CSV_EXPORT_DIR,
    }.issubset(AppSetting.KNOWN_KEYS)


def test_model_column_defaults_match_defined_constants():
    assert ResearchRun.__table__.c.status.default.arg == ResearchRun.STATUS_PENDING
    assert Product.__table__.c.judgement.default.arg == Product.JUDGEMENT_UNKNOWN
    assert Product.__table__.c.status.default.arg == Product.STATUS_UNREVIEWED


def test_models_are_registered_in_metadata(app):
    with app.app_context():
        table_names = set(db.metadata.tables.keys())

    assert "research_runs" in table_names
    assert "products" in table_names
    assert "product_research_runs" in table_names
    assert "app_settings" in table_names


def test_expected_tables_exist(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())

    assert "research_runs" in table_names
    assert "products" in table_names
    assert "product_research_runs" in table_names
    assert "app_settings" in table_names


def test_unique_constraints_exist_on_asin_and_app_setting_key(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        inspector = inspect(db.engine)
        product_indexes = inspector.get_indexes("products")
        app_setting_indexes = inspector.get_indexes("app_settings")

    assert any(
        index["name"] == "ix_products_asin" and index.get("unique")
        for index in product_indexes
    )
    assert any(
        index["name"] == "ix_app_settings_key" and index.get("unique")
        for index in app_setting_indexes
    )


def test_foreign_keys_exist_on_product_research_runs(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        inspector = inspect(db.engine)
        foreign_keys = inspector.get_foreign_keys("product_research_runs")
        referred_tables = {fk["referred_table"] for fk in foreign_keys}

    assert len(foreign_keys) == 2
    assert "products" in referred_tables
    assert "research_runs" in referred_tables


def test_research_run_can_be_created(app, db_schema):
    with app.app_context():
        run = ResearchRun(name="test run", keyword="camera")
        db.session.add(run)
        db.session.commit()

        assert run.id is not None


def test_product_can_be_created(app, db_schema):
    with app.app_context():
        product = Product(asin="B000TEST01", title="Sample Product")
        db.session.add(product)
        db.session.commit()

        assert product.id is not None


def test_product_asin_is_required(app, db_schema):
    with app.app_context():
        product = Product(title="Missing ASIN")
        db.session.add(product)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_product_asin_is_unique(app, db_schema):
    with app.app_context():
        first = Product(asin="B000UNIQUE1", title="First")
        second = Product(asin="B000UNIQUE1", title="Second")
        db.session.add(first)
        db.session.commit()

        db.session.add(second)
        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_app_setting_key_is_unique(app, db_schema):
    with app.app_context():
        first = AppSetting(key="default_domain", value="5")
        second = AppSetting(key="default_domain", value="1")
        db.session.add(first)
        db.session.commit()

        db.session.add(second)
        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_product_research_run_links_product_and_research_run(app, db_schema):
    with app.app_context():
        product = Product(asin="B000LINK01", title="Linked Product")
        run = ResearchRun(name="Link Run")
        db.session.add_all([product, run])
        db.session.commit()

        link = ProductResearchRun(product_id=product.id, research_run_id=run.id)
        db.session.add(link)
        db.session.commit()

        assert link.id is not None
        assert link.product.id == product.id
        assert link.research_run.id == run.id
        assert product.research_links[0].id == link.id
        assert run.product_links[0].id == link.id
