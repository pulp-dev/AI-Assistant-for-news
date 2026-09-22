from pathlib import Path

from ftk_mcp.parser import parse_product, parse_product_links

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_product():
    html = (FIXTURES / "product.html").read_text(encoding="utf-8")
    p = parse_product(html, "https://www.f-tk.ru/catalog/item-1541945/")
    assert p.title.startswith("Дождевик")
    assert p.sku == "87489497"
    assert p.price_segment == "Эконом"
    assert p.retail_price_rub == 480.0
    assert p.characteristics["Основной материал"] == "100% ПВХ"
    assert p.characteristics["ТР ТС"] == "019/2011"
    assert len(p.variants) == 2
    assert p.certificates[0]["url"] == "https://www.f-tk.ru/upload/cert.pdf"
    assert p.item_id == "1541945"


def test_parse_search_results():
    html = (FIXTURES / "search.html").read_text(encoding="utf-8")
    rows = parse_product_links(html, "https://www.f-tk.ru", limit=10)
    assert len(rows) == 2
    assert rows[0].sku == "87491008"
    assert rows[0].price_rub == 2550.0
    assert rows[1].url.endswith("/catalog/item-1541945/")
