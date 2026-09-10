import pathlib

from ro_collector.parse_merchant import parse_merchant_page, parse_price, total_pages

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_price():
    assert parse_price("39,950,000 z") == 39_950_000
    assert parse_price("22,314 z") == 22_314


def test_total_pages():
    assert total_pages(12392) == 620
    assert total_pages(20) == 1
    assert total_pages(21) == 2


def test_past_end_page_returns_empty_not_error():
    """A page paginated past the last record has no listing table. That is
    end-of-data, not a parse error -- it must return an empty page, never raise."""
    html = "<html><body><p>Total of 65 records</p><div>No results.</div></body></html>"
    page = parse_merchant_page(html, "vendors")
    assert page.rows == []
    assert page.total_records == 65


def test_vendors_page_shape():
    page = parse_merchant_page(load("vendors_p1.html"), kind="vendors")
    assert len(page.rows) == 20
    assert page.total_records > 10_000
    for row in page.rows:
        assert row.item_id > 0
        assert row.price > 0
        assert row.amount > 0
        assert row.map != "" and row.x > 0 and row.y > 0
        assert row.merchant != ""
        assert isinstance(row.refine, int)
        assert row.cards != ""


def test_vendors_refine_parsed_out_of_name():
    page = parse_merchant_page(load("vendors_p1.html"), kind="vendors")
    # No parsed item_name may still carry a leading refine marker
    assert not any(r.item_name.lstrip().startswith("+") for r in page.rows)


def test_buyers_page_shape():
    page = parse_merchant_page(load("buyers_p1.html"), kind="buyers")
    assert len(page.rows) == 20
    for row in page.rows:
        assert row.item_id > 0
        assert row.price > 0            # asking price
        assert row.refine == 0 and row.cards == "None"
