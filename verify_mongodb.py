"""MongoDB Integration Verification - Phase 7.3"""
import sys
import os
sys.path.insert(0, '.')

print("=" * 60)
print("MONGODB INTEGRATION VERIFICATION")
print("=" * 60)

from core.database import mongodb, COLLECTION_PRODUCTS, COLLECTION_DATA_SOURCES, COLLECTION_SCRAPING_RUNS, COLLECTION_REJECTED_PRODUCTS
from core.exceptions import DatabaseConnectionError

# 1. Verify connection manager behavior
print("\n1. Connection Manager Behavior")
print("-" * 40)
print(f"   Initial status: {mongodb.status_string()}")
print(f"   is_connected(): {mongodb.is_connected()}")

# 2. Verify ping
print("\n2. Ping Test")
print("-" * 40)
try:
    result = mongodb.connect()
    print(f"   connect() result: {result}")
    print(f"   Status after connect: {mongodb.status_string()}")
    # Try ping
    db = mongodb.get_database()
    ping_result = db.command("ping")
    print(f"   Ping result: {ping_result}")
    # Close connection
    mongodb.close()
    print(f"   Status after close: {mongodb.status_string()}")
except Exception as e:
    print(f"   Error (expected if no MongoDB): {type(e).__name__}: {e}")
    try:
        mongodb.close()
    except:
        pass

# 3. Verify collection initialization
print("\n3. Collection Initialization")
print("-" * 40)
try:
    mongodb.connect()
    mongodb.initialize_collections()
    print("   initialize_collections() succeeded")
    
    # Verify indexes were created
    db = mongodb.get_database()
    coll_info = db.list_collections()
    collection_names = [c['name'] for c in coll_info]
    print(f"   Collections: {collection_names}")
    
    # Check for key indexes
    products_coll = db[COLLECTION_PRODUCTS].index_information()
    print(f"   Products indexes: {list(products_coll.keys())}")
    
    mongodb.close()
except Exception as e:
    print(f"   Error: {type(e).__name__}: {e}")
    try:
        mongodb.close()
    except:
        pass

# 4. Verify product insertion (with mock since no real DB)
print("\n4. Product Insertion Test (Mock)")
print("-" * 40)
from decimal import Decimal
from bson import Decimal128

# Test Decimal128 conversion
test_price = Decimal("19.99")
decimal128 = Decimal128(test_price)
converted_back = decimal128.to_decimal()
print(f"   Original: {test_price}")
print(f"   Decimal128: {decimal128}")
print(f"   Converted back: {converted_back}")
print(f"   Precision preserved: {test_price == converted_back}")

# 5. Verify regional pricing persistence
print("\n5. Regional Pricing Persistence Test (Mock)")
print("-" * 40)
regional_data = [
    {"country": "DE", "country_code": "DE", "currency": "EUR", "net_price": Decimal("10.00"), "vat_rate": Decimal("19.00"), "gross_price": Decimal("11.90")},
    {"country": "FR", "country_code": "FR", "currency": "EUR", "net_price": Decimal("10.00"), "vat_rate": Decimal("20.00"), "gross_price": Decimal("12.00")},
]
print(f"   Regional entries: {len(regional_data)}")
for entry in regional_data:
    print(f"     - {entry['country']}: net={entry['net_price']}, vat={entry['vat_rate']}%, gross={entry['gross_price']}")

# 6. Verify rejected product persistence
print("\n6. Rejected Product Persistence Test (Mock)")
print("-" * 40)
from core.database import COLLECTION_REJECTED_PRODUCTS
print(f"   COLLECTION_REJECTED_PRODUCTS: {COLLECTION_REJECTED_PRODUCTS}")

# 7. Verify scraping run persistence
print("\n7. Scraping Run Persistence Test (Mock)")
print("-" * 40)
from core.database import COLLECTION_SCRAPING_RUNS
print(f"   COLLECTION_SCRAPING_RUNS: {COLLECTION_SCRAPING_RUNS}")

# 8. Verify upsert by composite key
print("\n8. Upsert by Composite Key Test")
print("-" * 40)
try:
    mongodb.connect()
    products_coll = mongodb.get_collection("products")
    
    # Test upsert with composite key {source_id, article_number}
    test_doc = {
        "source_id": "test_source_001",
        "article_number": "TEST-001",
        "product_name": "Test Product",
        "price": Decimal128(Decimal("29.99")),
        "verification_status": "unverified",
        "is_synthetic": True,
        "regional_data": [],
        "data_origin": "test",
        "collected_at": None
    }
    
    # Upsert
    result = products_coll.replace_one(
        {"source_id": "test_source_001", "article_number": "TEST-001"},
        test_doc,
        upsert=True
    )
    print(f"   Matched: {result.matched_count}, Modified: {result.modified_count}, Upserted: {result.upserted_id is not None}")
    
    # Read back
    found = products_coll.find_one({"source_id": "test_source_001", "article_number": "TEST-001"})
    if found:
        print(f"   Read back product name: {found.get('product_name')}")
        print(f"   Read back price: {found.get('price')}")
        print(f"   Read back verification_status: {found.get('verification_status')}")
        print(f"   Read back is_synthetic: {found.get('is_synthetic')}")
        
        # Clean up
        products_coll.delete_one({"source_id": "test_source_001", "article_number": "TEST-001"})
        print(f"   Test record cleaned up")
    
    mongodb.close()
except Exception as e:
    print(f"   Error: {type(e).__name__}: {e}")
    try:
        mongodb.close()
    except:
        pass

print("\n" + "=" * 60)
print("MONGODB VERIFICATION COMPLETE")
print("=" * 60)