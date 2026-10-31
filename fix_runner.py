"""Fix runner.py - add source_domain parameter to _extract_products_from_page."""
import sys

with open('scraper/runner.py') as f:
    content = f.read()

# Fix 1: Add source_domain parameter to _extract_products_from_page definition
old_def = """    def _extract_products_from_page(
        self,
        soup,
        page_url: str,
        result: ExtractionResult,
        data_origin: str,
    ) -> int:
        \"\"\"Extract products from a single page. Returns count found on page.\"\"\""""

new_def = """    def _extract_products_from_page(
        self,
        soup,
        page_url: str,
        result: ExtractionResult,
        data_origin: str,
        source_domain: str,
    ) -> int:
        \"\"\"Extract products from a single page. Returns count found on page.\"\"\""""

content = content.replace(old_def, new_def)
print("Fix 1: Added source_domain parameter to _extract_products_from_page definition")

# Fix 2: Update the call site to pass source_domain
old_call = "extracted = self._extract_products_from_page(\n                soup, response.url, result, data_origin\n            )"
new_call = "extracted = self._extract_products_from_page(\n                soup, response.url, result, data_origin, source_domain\n            )"

content = content.replace(old_call, new_call)
print("Fix 2: Updated _extract_products_from_page call to pass source_domain")

# Write the fixed file
with open('scraper/runner.py', 'w') as f:
    f.write(content)

print("Fix applied successfully. Writing complete.")
print(f"Total length: {len(content)} chars")