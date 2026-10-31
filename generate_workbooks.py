"""Generate Excel workbooks for Phase 7.6"""
import sys
sys.path.insert(0, '.')

from exporters.excel_exporter import export_granit_eu, export_blinkit_bengaluru
from decimal import Decimal
from typing import List, Dict, Any

print("=" * 60)
print("EXCEL WORKBOOK GENERATION")
print("=" * 60)

# Create synthetic products for GRANIT EU export
products = [
    {
        "article_number": "GRANIT-001",
        "product_name": "Test Precision Screw M8",
        "sku": "GR8-M8",
        "ean_gtin": "4015284984321",
        "description": "Precision screw for industrial applications",
        "product_type": "fastener",
        "manufacturer": "GRANIT EU GmbH",
        "brand": "GRANIT",
        "category": "Hardware",
        "subcategory": "Screws",
        "price": Decimal("15.50"),
        "currency": "EUR",
        "data_origin": "approved_public_source",
        "source_id": "source_001",
        "source_url": "https://example.com/grantin-001",
        "verification_status": "verified",
        "is_synthetic": False,
        "regional_data": [
            {"country": "Germany", "country_code": "DE", "currency": "EUR", "net_price": Decimal("12.00"), "vat_rate": Decimal("19.00"), "gross_price": Decimal("14.28")},
            {"country": "France", "country_code": "FR", "currency": "EUR", "net_price": Decimal("12.00"), "vat_rate": Decimal("20.00"), "gross_price": Decimal("14.40")},
        ],
        "collected_at": "2024-01-15T10:30:00Z",
        "last_updated_at": "2024-01-15T10:30:00Z",
    },
    {
        "article_number": "GRANIT-002",
        "product_name": "Test Bolt M12",
        "sku": "GR12-BOLT",
        "ean_gtin": "4015284984322",
        "description": "Industrial bolt for construction",
        "product_type": "fastener",
        "manufacturer": "GRANIT EU GmbH",
        "brand": "GRANIT",
        "category": "Hardware",
        "subcategory": "Bolts",
        "price": Decimal("25.00"),
        "currency": "EUR",
        "data_origin": "approved_public_source",
        "source_id": "source_002",
        "source_url": "https://example.com/grantin-002",
        "verification_status": "verified",
        "is_synthetic": False,
        "regional_data": [
            {"country": "Germany", "country_code": "DE", "currency": "EUR", "net_price": Decimal("18.00"), "vat_rate": Decimal("19.00"), "gross_price": Decimal("21.42")},
        ],
        "collected_at": "2024-01-15T10:30:00Z",
        "last_updated_at": "2024-01-15T10:30:00Z",
    },
    {
        "article_number": "GRANIT-003",
        "product_name": "Test Washer 10mm",
        "sku": "GR10-WSH",
        "ean_gtin": "4015284984323",
        "description": "Flat washer for machinery",
        "product_type": "fastener",
        "manufacturer": "GRANIT EU GmbH",
        "brand": "GRANIT",
        "category": "Hardware",
        "subcategory": "Washers",
        "price": Decimal("5.99"),
        "currency": "EUR",
        "data_origin": "synthetic",
        "source_id": "source_test",
        "source_url": "https://example.com/grantin-003",
        "verification_status": "not_verified",
        "is_synthetic": True,
        "regional_data": [
            {"country": "Germany", "country_code": "DE", "currency": "EUR", "net_price": Decimal("3.50"), "vat_rate": Decimal("19.00"), "gross_price": Decimal("4.17")},
        ],
        "collected_at": "2024-01-15T10:30:00Z",
        "last_updated_at": "2024-01-15T10:30:00Z",
    },
]

print(f"Created {len(products)} synthetic products for Excel export")

# Export GRANIT EU workbook
print("\n1. Generating GRANIT_Parts_EU_Sample_Dataset.xlsx...")
try:
    granit_buf = export_granit_eu(products)
    with open('output/GRANIT_Parts_EU_Sample_Dataset.xlsx', 'wb') as f:
        f.write(granit_buf.getvalue())
    print(f"   Saved GRANIT workbook: {len(granit_buf.getvalue())} bytes")
except Exception as e:
    print(f"   Error generating GRANIT workbook: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Export Blinkit workbook (with synthetic data)
print("\n2. Generating Blinkit_Bengaluru_Sample_Dataset.xlsx...")
blinkit_products = [
    {
        "product_id": "BLNK-001",
        "sku": "BLN-K001",
        "product_name": "Test Food Item",
        "brand": "Test Brand",
        "category": "Food",
        "subcategory": "Packaged",
        "product_description": "Test food product for Blinkit dataset",
        "barcode": "8901234567890",
        "product_url": "https://example.com/blinkit-001",
        "image_url": "https://example.com/image.jpg",
        "price": Decimal("45.00"),
        "currency": "INR",
        "data_origin": "approved_public_source",
    },
    {
        "product_id": "BLNK-002",
        "sku": "BLN-K002",
        "product_name": "Test Electronics",
        "brand": "TechBrand",
        "category": "Electronics",
        "subcategory": "Accessories",
        "product_description": "Test electronics product for Blinkit dataset",
        "barcode": "8901234567891",
        "product_url": "https://example.com/blinkit-002",
        "image_url": "https://example.com/image2.jpg",
        "price": Decimal("120.00"),
        "currency": "INR",
        "data_origin": "approved_public_source",
    },
    {
        "product_id": "BLNK-003",
        "sku": "BLN-K003",
        "product_name": "Test Home Item",
        "brand": "HomeEssentials",
        "category": "Home",
        "subcategory": "Kitchen",
        "product_description": "Test home product for Blinkit dataset",
        "barcode": "8901234567892",
        "product_url": "https://example.com/blinkit-003",
        "image_url": "https://example.com/image3.jpg",
        "price": Decimal("89.50"),
        "currency": "INR",
        "data_origin": "synthetic",
    },
]

try:
    blinkit_buf = export_blinkit_bengaluru(blinkit_products)
    with open('output/Blinkit_Bengaluru_Sample_Dataset.xlsx', 'wb') as f:
        f.write(blinkit_buf.getvalue())
    print(f"   Saved Blinkit workbook: {len(blinkit_buf.getvalue())} bytes")
except Exception as e:
    print(f"   Error generating Blinkit workbook: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("EXCEL WORKBOOK GENERATION COMPLETE")
print("=" * 60)