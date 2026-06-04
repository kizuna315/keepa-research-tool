from datetime import datetime

from app.extensions import db


class ResearchRun(db.Model):
    __tablename__ = "research_runs"

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    VALID_STATUSES = {
        STATUS_PENDING,
        STATUS_RUNNING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    keyword = db.Column(db.String(255), nullable=True)
    category_id = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default=STATUS_PENDING)
    conditions_json = db.Column(db.Text, nullable=True)
    total_requested = db.Column(db.Integer, nullable=False, default=0)
    total_fetched = db.Column(db.Integer, nullable=False, default=0)
    total_saved = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    product_links = db.relationship(
        "ProductResearchRun",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<ResearchRun {self.id} status={self.status}>"


class Product(db.Model):
    __tablename__ = "products"

    JUDGEMENT_GOOD = "good"
    JUDGEMENT_WATCH = "watch"
    JUDGEMENT_BAD = "bad"
    JUDGEMENT_UNKNOWN = "unknown"

    VALID_JUDGEMENTS = {
        JUDGEMENT_GOOD,
        JUDGEMENT_WATCH,
        JUDGEMENT_BAD,
        JUDGEMENT_UNKNOWN,
    }

    STATUS_UNREVIEWED = "unreviewed"
    STATUS_CANDIDATE = "candidate"
    STATUS_HOLD = "hold"
    STATUS_EXCLUDED = "excluded"
    STATUS_SUPPLIER_SEARCH_PENDING = "supplier_search_pending"

    VALID_STATUSES = {
        STATUS_UNREVIEWED,
        STATUS_CANDIDATE,
        STATUS_HOLD,
        STATUS_EXCLUDED,
        STATUS_SUPPLIER_SEARCH_PENDING,
    }

    id = db.Column(db.Integer, primary_key=True)
    asin = db.Column(db.String(32), nullable=False, unique=True, index=True)
    jan = db.Column(db.String(32), nullable=True)
    ean = db.Column(db.String(32), nullable=True)
    title = db.Column(db.String(512), nullable=False)
    brand = db.Column(db.String(255), nullable=True)
    manufacturer = db.Column(db.String(255), nullable=True)
    category_id = db.Column(db.String(64), nullable=True)
    category_name = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.Text, nullable=True)
    amazon_url = db.Column(db.Text, nullable=True)
    keepa_url = db.Column(db.Text, nullable=True)

    current_price = db.Column(db.Integer, nullable=True)
    avg_price_30 = db.Column(db.Integer, nullable=True)
    avg_price_90 = db.Column(db.Integer, nullable=True)
    lowest_price_90 = db.Column(db.Integer, nullable=True)
    highest_price_90 = db.Column(db.Integer, nullable=True)

    sales_rank_current = db.Column(db.Integer, nullable=True)
    sales_rank_avg_30 = db.Column(db.Integer, nullable=True)
    sales_rank_avg_90 = db.Column(db.Integer, nullable=True)
    sales_rank_drops_30 = db.Column(db.Integer, nullable=True)
    sales_rank_drops_90 = db.Column(db.Integer, nullable=True)

    new_offer_count = db.Column(db.Integer, nullable=True)
    used_offer_count = db.Column(db.Integer, nullable=True)
    fba_offer_count = db.Column(db.Integer, nullable=True)

    amazon_in_stock = db.Column(db.Boolean, nullable=True)
    amazon_was_in_stock_90 = db.Column(db.Boolean, nullable=True)

    review_count = db.Column(db.Integer, nullable=True)
    rating = db.Column(db.Float, nullable=True)

    price_stability_score = db.Column(db.Integer, nullable=True)
    sales_score = db.Column(db.Integer, nullable=True)
    competition_score = db.Column(db.Integer, nullable=True)
    risk_score = db.Column(db.Integer, nullable=True)
    keepa_score = db.Column(db.Integer, nullable=True)

    judgement = db.Column(
        db.String(32),
        nullable=False,
        default=JUDGEMENT_UNKNOWN,
    )
    status = db.Column(db.String(32), nullable=False, default=STATUS_UNREVIEWED)
    memo = db.Column(db.Text, nullable=True)

    raw_keepa_json = db.Column(db.Text, nullable=True)
    first_seen_at = db.Column(db.DateTime, nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    research_links = db.relationship(
        "ProductResearchRun",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Product {self.asin}>"


class ProductResearchRun(db.Model):
    __tablename__ = "product_research_runs"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    research_run_id = db.Column(
        db.Integer,
        db.ForeignKey("research_runs.id"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    product = db.relationship("Product", back_populates="research_links")
    research_run = db.relationship("ResearchRun", back_populates="product_links")

    def __repr__(self):
        return (
            f"<ProductResearchRun product_id={self.product_id} "
            f"research_run_id={self.research_run_id}>"
        )


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    KEY_KEEPA_API_KEY = "keepa_api_key"
    KEY_DEFAULT_DOMAIN_ID = "default_domain_id"
    KEY_DEFAULT_MIN_PRICE = "default_min_price"
    KEY_DEFAULT_MAX_PRICE = "default_max_price"
    KEY_DEFAULT_MIN_OFFER_COUNT = "default_min_offer_count"
    KEY_DEFAULT_MAX_OFFER_COUNT = "default_max_offer_count"
    KEY_EXCLUDE_AMAZON_IN_STOCK = "exclude_amazon_in_stock"
    KEY_DEFAULT_MIN_SALES_RANK_DROPS_90 = "default_min_sales_rank_drops_90"
    KEY_CSV_EXPORT_DIR = "csv_export_dir"

    KNOWN_KEYS = {
        KEY_KEEPA_API_KEY,
        KEY_DEFAULT_DOMAIN_ID,
        KEY_DEFAULT_MIN_PRICE,
        KEY_DEFAULT_MAX_PRICE,
        KEY_DEFAULT_MIN_OFFER_COUNT,
        KEY_DEFAULT_MAX_OFFER_COUNT,
        KEY_EXCLUDE_AMAZON_IN_STOCK,
        KEY_DEFAULT_MIN_SALES_RANK_DROPS_90,
        KEY_CSV_EXPORT_DIR,
    }

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), nullable=False, unique=True, index=True)
    value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f"<AppSetting {self.key}>"
