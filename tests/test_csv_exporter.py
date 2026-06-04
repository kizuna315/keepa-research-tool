import csv
import re
from datetime import datetime
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Product
from app.services.csv_exporter import CsvExporter, CsvExporterError


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def export_dir(isolated_dirs):
    return isolated_dirs["root"] / "csv_exports"


def _product(**kwargs):
    defaults = {
        "asin": "B0CSV00001",
        "jan": "4900000000001",
        "ean": "4900000000002",
        "title": "テスト商品",
        "brand": "テストブランド",
        "current_price": 1980,
        "avg_price_90": 2100,
        "new_offer_count": 5,
        "amazon_in_stock": False,
        "review_count": 12,
        "rating": 4.5,
        "sales_rank_drops_90": 24,
        "price_stability_score": 20,
        "sales_score": 35,
        "competition_score": 25,
        "risk_score": 10,
        "keepa_score": 90,
        "judgement": Product.JUDGEMENT_GOOD,
        "status": Product.STATUS_CANDIDATE,
        "amazon_url": "https://www.amazon.co.jp/dp/B0CSV00001",
        "keepa_url": "https://keepa.com/#!product/5-B0CSV00001",
        "memo": "メモ",
        "last_checked_at": datetime(2026, 5, 26, 15, 30, 0),
    }
    defaults.update(kwargs)
    return Product(**defaults)


def _read_csv(filepath):
    with open(filepath, encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.reader(csv_file))


def test_build_default_filepath_uses_expected_filename(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).build_default_filepath()
    path = Path(filepath)

    assert path.parent == export_dir
    assert re.fullmatch(r"keepa_research_\d{8}_\d{6}\.csv", path.name)


def test_export_products_creates_csv_file(export_dir):
    filepath = export_dir / "products.csv"

    returned = CsvExporter(export_dir=str(export_dir)).export_products(
        [_product()], filepath=str(filepath)
    )

    assert returned == str(filepath)
    assert filepath.exists()


def test_export_products_writes_utf8_bom(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products([_product()])

    with open(filepath, "rb") as csv_file:
        assert csv_file.read(3) == b"\xef\xbb\xbf"


def test_export_products_writes_headers_in_expected_order(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products([_product()])

    rows = _read_csv(filepath)
    assert rows[0] == CsvExporter.HEADERS


def test_export_products_round_trips_japanese_title(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products(
        [_product(title="日本語商品名")]
    )

    rows = _read_csv(filepath)
    assert rows[1][2] == "日本語商品名"


def test_export_products_converts_none_to_empty_string(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products(
        [_product(jan=None, ean=None, brand=None, memo=None)]
    )

    rows = _read_csv(filepath)
    assert rows[1][1] == ""
    assert rows[1][3] == ""
    assert rows[1][20] == ""


def test_export_products_outputs_datetime_as_string(export_dir):
    checked_at = datetime(2026, 5, 26, 15, 30, 0)
    filepath = CsvExporter(export_dir=str(export_dir)).export_products(
        [_product(last_checked_at=checked_at)]
    )

    rows = _read_csv(filepath)
    assert rows[1][21] == "2026-05-26 15:30:00"


def test_export_products_outputs_product_fields(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products([_product()])

    rows = _read_csv(filepath)
    row = rows[1]
    assert row[0] == "B0CSV00001"
    assert row[1] == "4900000000001"
    assert row[4] == "1980"
    assert row[7] == "False"
    assert row[16] == Product.JUDGEMENT_GOOD
    assert row[17] == Product.STATUS_CANDIDATE
    assert row[18] == "https://www.amazon.co.jp/dp/B0CSV00001"
    assert row[19] == "https://keepa.com/#!product/5-B0CSV00001"


def test_export_candidates_exports_only_candidate_products(app, db_schema, export_dir):
    with app.app_context():
        db.session.add(
            _product(
                asin="B0CAND0001",
                title="候補商品",
                status=Product.STATUS_CANDIDATE,
            )
        )
        db.session.add(
            _product(
                asin="B0EXCL0001",
                title="除外商品",
                status=Product.STATUS_EXCLUDED,
            )
        )
        db.session.commit()

        filepath = CsvExporter(export_dir=str(export_dir)).export_candidates()

    rows = _read_csv(filepath)
    assert len(rows) == 2
    assert rows[1][0] == "B0CAND0001"
    assert "除外商品" not in str(rows)


def test_exporter_creates_missing_output_directory(export_dir):
    missing_export_dir = export_dir / "missing" / "exports"

    filepath = CsvExporter(export_dir=str(missing_export_dir)).export_products([_product()])

    assert missing_export_dir.exists()
    assert Path(filepath).exists()


def test_export_products_raises_csv_exporter_error_on_write_failure(export_dir):
    exporter = CsvExporter(export_dir=str(export_dir))

    with pytest.raises(CsvExporterError) as exc_info:
        exporter.export_products([_product()], filepath=str(export_dir))
    assert "CSV出力中にエラーが発生しました。" in str(exc_info.value)


def test_export_headers_have_22_columns_and_do_not_include_raw_keepa_json():
    assert len(CsvExporter.HEADERS) == 22
    assert "raw_keepa_json" not in CsvExporter.HEADERS


def test_export_products_does_not_write_raw_keepa_json_value(export_dir):
    product = _product()
    product.raw_keepa_json = "secret raw keepa payload"

    filepath = CsvExporter(export_dir=str(export_dir)).export_products([product])

    with open(filepath, encoding="utf-8-sig", newline="") as csv_file:
        csv_text = csv_file.read()

    assert "raw_keepa_json" not in csv_text
    assert "secret raw keepa payload" not in csv_text


def test_export_products_masks_sensitive_memo(export_dir):
    filepath = CsvExporter(export_dir=str(export_dir)).export_products(
        [_product(memo="memo key=SECRET_KEEPA_KEY_123 Authorization: Bearer SECRET_TOKEN_456")]
    )

    with open(filepath, encoding="utf-8-sig", newline="") as csv_file:
        csv_text = csv_file.read()

    assert "SECRET_KEEPA_KEY_123" not in csv_text
    assert "SECRET_TOKEN_456" not in csv_text
    assert "[REDACTED]" in csv_text


def test_export_products_write_error_raises_safe_error(export_dir):
    secret = "SECRET_KEEPA_KEY_123"
    exporter = CsvExporter(export_dir=str(export_dir))

    with pytest.raises(CsvExporterError) as exc_info:
        exporter.export_products(
            [_product(memo=f"key={secret}")],
            filepath=str(export_dir),
        )

    assert secret not in str(exc_info.value)
    assert "CSV出力中にエラーが発生しました。" in str(exc_info.value)


def test_export_candidates_write_error_does_not_leak_secret(app, db_schema, export_dir):
    secret = "SECRET_KEEPA_KEY_123"
    with app.app_context():
        db.session.add(_product(memo=f"apiKey={secret}", status=Product.STATUS_CANDIDATE))
        db.session.commit()

        with pytest.raises(CsvExporterError) as exc_info:
            CsvExporter(export_dir=str(export_dir)).export_candidates(filepath=str(export_dir))

    assert secret not in str(exc_info.value)
