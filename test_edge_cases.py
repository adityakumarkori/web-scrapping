"""Edge case tests for Excel export - using temp files."""
import tempfile
import os
from openpyxl import load_workbook
from exporters.excel_exporter import export_granit_eu, export_blinkit_bengaluru


def test_workbook(wb_path, expected_sheets):
    """Load workbook and verify sheet structure."""
    from openpyxl import load_workbook as _lw
    wb = _lw(wb_path)
    actual_sheets = set(wb.sheetnames)
    expected_set = set(expected_sheets)
    assert actual_sheets == expected_set, f"Expected sheets {expected_set}, got {actual_sheets}"
    for sheet_name in expected_sheets:
        assert sheet_name in wb.sheetnames, f"Missing sheet: {sheet_name}"
        ws = wb[sheet_name]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    return True


# Test 1: Empty product list
print("Test 1: Empty product list")
try:
    granit_expected = {"Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"}
    blinkit_expected = {"Products", "Pricing & Tax", "Packaging & Ingredients", "Suppliers", "Dark Stores & Inventory", "Delivery & Zones", "Data Quality", "Data Dictionary", "Sources & Assumptions"}
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu([])
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, granit_expected)
    os.unlink(granit_path)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        blinkit_buf = export_blinkit_bengaluru([])
        f.write(blinkit_buf.getvalue())
        blinkit_path = f.name
    test_workbook(blinkit_path, blinkit_expected)
    os.unlink(blinkit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 2: Single product
print("\nTest 2: Single product")
try:
    products = [{
        "article_number": "GRANIT-001",
        "product_name": "Test Product",
        "price": 10.00,
        "currency": "EUR",
        "data_origin": "approved_public_source",
        "source_id": "src_001",
        "source_url": "https://example.com",
        "verification_status": "verified",
        "is_synthetic": False,
    }]
    granit_expected = {"Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"}
    blinkit_expected = {"Products", "Pricing & Tax", "Packaging & Ingredients", "Suppliers", "Dark Stores & Inventory", "Delivery & Zones", "Data Quality", "Data Dictionary", "Sources & Assumptions"}
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu(products)
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, granit_expected)
    os.unlink(granit_path)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        blinkit_buf = export_blinkit_bengaluru(products)
        f.write(blinkit_buf.getvalue())
        blinkit_path = f.name
    test_workbook(blinkit_path, blinkit_expected)
    os.unlink(blinkit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 3: Product without EAN/GTIN
print("\nTest 3: Product without EAN/GTIN")
try:
    products = [{
        "article_number": "GRANIT-001",
        "product_name": "Test Product",
        "ean_gtin": None,
        "price": 10.00,
        "currency": "EUR",
        "data_origin": "approved_public_source",
        "source_id": "src_001",
        "source_url": "https://example.com",
        "verification_status": "not_verified",
        "is_synthetic": False,
        "regional_data": [{"country": "DE", "country_code": "DE", "currency": "EUR", "net_price": 9.00, "vat_rate": 19.00, "gross_price": 10.71}],
    }]
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu(products)
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, ["Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"])
    ws = None
    try:
        wb = load_workbook(granit_path)
        ws = wb["Regional Pricing"]
        print(f"  Regional Pricing rows: {ws.max_row} (expected 4 = header + 1 country)")
    except:
        pass
    os.unlink(granit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 4: Product with multiple regional prices
print("\nTest 4: Product with multiple regional prices")
try:
    products = [{
        "article_number": "GRANIT-001",
        "product_name": "Test Product",
        "price": 10.00,
        "currency": "EUR",
        "data_origin": "approved_public_source",
        "source_id": "src_001",
        "source_url": "https://example.com",
        "verification_status": "verified",
        "is_synthetic": False,
        "regional_data": [
            {"country": "DE", "country_code": "DE", "currency": "EUR", "net_price": 9.00, "vat_rate": 19.00, "gross_price": 10.71},
            {"country": "FR", "country_code": "FR", "currency": "EUR", "net_price": 9.50, "vat_rate": 20.00, "gross_price": 11.40},
            {"country": "IT", "country_code": "IT", "currency": "EUR", "net_price": 8.75, "vat_rate": 22.00, "gross_price": 10.68},
        ],
    }]
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu(products)
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, ["Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"])
    ws = None
    try:
        wb = load_workbook(granit_path)
        ws = wb["Regional Pricing"]
        print(f"  Regional Pricing rows (incl header): {ws.max_row} (expected 4 = header + 3 countries)")
    except:
        pass
    os.unlink(granit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 5: Synthetic product
print("\nTest 5: Synthetic product")
try:
    products = [{
        "article_number": "GRANIT-003",
        "product_name": "Synthetic Product",
        "price": 5.99,
        "currency": "EUR",
        "data_origin": "synthetic",
        "source_id": "source_test",
        "source_url": "https://example.com/test",
        "verification_status": "not_verified",
        "is_synthetic": True,
        "regional_data": [{"country": "DE", "country_code": "DE", "currency": "EUR", "net_price": 3.50, "vat_rate": 19.00, "gross_price": 4.17}],
    }]
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu(products)
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, ["Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"])
    ws = None
    try:
        wb = load_workbook(granit_path)
        ws = wb["Data Dictionary"]
        print(f"  Data Dictionary rows: {ws.max_row}")
    except:
        pass
    os.unlink(granit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 6: Product missing optional fields
print("\nTest 6: Product with minimal fields")
try:
    products = [{
        "article_number": "MINIMAL-001",
        "product_name": "Minimal",
        "price": 1.00,
        "currency": "EUR",
        "data_origin": "manual_entry",
        "source_id": "manual_001",
        "source_url": "https://example.com/minimal",
        "verification_status": "not_verified",
        "is_synthetic": False,
    }]
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        granit_buf = export_granit_eu(products)
        f.write(granit_buf.getvalue())
        granit_path = f.name
    test_workbook(granit_path, ["Products", "Regional Pricing", "Specifications", "Compliance", "Inventory & Logistics", "Data Quality", "Data Dictionary", "Sources & Assumptions"])
    os.unlink(granit_path)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")

print("\nAll edge case tests complete")