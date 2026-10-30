"""Final Pydantic product data model for the GRANIT EU dataset.

Organizes product data into logical sections:

A. Product master
B. Manufacturer and classification
C. Technical specifications
D. Compliance
E. Inventory and logistics

Plus a nested ``regional_data`` structure supporting multiple EU
country-specific commercial records, and data provenance fields.

Unavailable or restricted information supports null values. No actual
product information is hardcoded.
"""

from datetime import datetime
from decimal import Decimal
import re
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


DATA_ORIGINS = {
    "approved_public_source",
    "authorized_api",
    "manual_entry",
    "synthetic",
}

VERIFICATION_STATUSES = {
    "verified",
    "partially_verified",
    "not_verified",
    "pending",
}

SOURCE_TYPES = {"website", "api", "csv", "manual"}


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Coerce a numeric-like value to Decimal, preserving None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class RegionalDataEntry(BaseModel):
    """A country-specific commercial record for a single product.

    A product can be sold in multiple EU countries, each with its own
    currency, price and VAT rate. None of these are assumed to apply to
    every EU country.
    """

    country: str = Field(..., min_length=1, description="Country name")
    country_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code (e.g. DE)",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (e.g. EUR)",
    )
    net_price: Optional[Decimal] = Field(
        default=None, description="Net price excluding VAT"
    )
    vat_rate: Optional[Decimal] = Field(
        default=None, description="VAT rate in percent (0-100)"
    )
    gross_price: Optional[Decimal] = Field(
        default=None, description="Gross price including VAT"
    )
    price_source: Optional[str] = Field(
        default=None, description="Origin of the price data"
    )
    effective_date: Optional[datetime] = Field(
        default=None, description="Date the price became effective"
    )

    @field_validator("country_code")
    @classmethod
    def _validate_country_code(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError(
                "country_code must be a 2-letter uppercase ISO 3166-1 alpha-2 code"
            )
        return value

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("currency must be a 3-letter uppercase ISO 4217 code")
        return value

    @field_validator("net_price", "vat_rate", "gross_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Optional[Decimal]:
        return _to_decimal(value)

    @field_validator("net_price", "gross_price")
    @classmethod
    def _validate_non_negative(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is not None and value < 0:
            raise ValueError("monetary values must be non-negative")
        return value

    @field_validator("vat_rate")
    @classmethod
    def _validate_vat_range(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is not None and not (Decimal("0") <= value <= Decimal("100")):
            raise ValueError("vat_rate must be between 0 and 100")
        return value

    @model_validator(mode="after")
    def _validate_gross_price_consistency(self) -> "RegionalDataEntry":
        """Validate gross price consistency when all three values are present."""
        if (
            self.net_price is not None
            and self.vat_rate is not None
            and self.gross_price is not None
        ):
            expected = self.net_price * (Decimal("1") + self.vat_rate / Decimal("100"))
            if abs(self.gross_price - expected) > Decimal("0.01"):
                raise ValueError(
                    "gross_price is inconsistent with net_price and vat_rate"
                )
        return self


class Product(BaseModel):
    """A GRANIT EU product record.

    Mandatory identifiers:
        - article_number
        - product_name

    Optional business information may be null when unavailable.
    """

    # --- A. Product master ---
    article_number: str = Field(..., min_length=1, description="Unique article number")
    product_name: str = Field(..., min_length=1, description="Human readable product name")
    sku: Optional[str] = Field(default=None, description="Stock keeping unit")
    ean_gtin: Optional[str] = Field(default=None, description="EAN / GTIN barcode")
    description: Optional[str] = Field(default=None, description="Full product description")
    short_description: Optional[str] = Field(default=None, description="Short product description")
    product_type: Optional[str] = Field(default=None, description="Product type")
    product_url: Optional[str] = Field(default=None, description="Canonical product page URL")
    image_urls: Optional[List[str]] = Field(default=None, description="Product image URLs")

    # --- B. Manufacturer and classification ---
    manufacturer: Optional[str] = Field(default=None, description="Product manufacturer")
    brand: Optional[str] = Field(default=None, description="Product brand")
    supplier: Optional[str] = Field(default=None, description="Product supplier")
    category: Optional[str] = Field(default=None, description="Product category")
    subcategory: Optional[str] = Field(default=None, description="Product subcategory")

    # --- C. Technical specifications ---
    dimensions: Optional[dict[str, Any]] = Field(default=None, description="Product dimensions")
    weight: Optional[dict[str, Any]] = Field(default=None, description="Product weight")
    material: Optional[str] = Field(default=None, description="Product material")
    technical_specifications: Optional[dict[str, Any]] = Field(
        default=None, description="Technical specifications"
    )
    compatibility: Optional[str] = Field(default=None, description="Compatibility information")

    # --- D. Compliance ---
    ce_marking_status: Optional[str] = Field(default=None, description="CE marking status")
    applicable_regulations: Optional[List[str]] = Field(
        default=None, description="Applicable regulations"
    )
    compliance_certificates: Optional[List[str]] = Field(
        default=None, description="Compliance certificates"
    )
    country_of_origin: Optional[str] = Field(default=None, description="Country of origin")

    # --- E. Inventory and logistics ---
    inventory_status: Optional[str] = Field(default=None, description="Inventory status")
    inventory_quantity: Optional[int] = Field(default=None, description="Inventory quantity")
    warehouse: Optional[str] = Field(default=None, description="Warehouse location")
    shipping_method: Optional[str] = Field(default=None, description="Shipping method")
    delivery_days: Optional[int] = Field(default=None, description="Delivery days")

    # Top-level price (single-market offer; regional prices live in regional_data).
    price: Optional[Decimal] = Field(default=None, description="Product price")
    currency: Optional[str] = Field(
        default=None, min_length=3, max_length=3, description="ISO 4217 currency code"
    )

    # --- Regional data (multiple EU country entries) ---
    regional_data: Optional[List[RegionalDataEntry]] = Field(
        default=None, description="Country-specific commercial records"
    )

    # --- Data provenance ---
    data_origin: str = Field(
        default="manual_entry",
        description="Source the product data originated from",
    )
    source_id: Optional[str] = Field(default=None, description="Identifier of the source record")
    source_url: Optional[str] = Field(default=None, description="URL of the source record")
    collected_at: Optional[datetime] = Field(default=None, description="When the data was collected")
    verification_status: str = Field(
        default="not_verified",
        description="Verification status of the product record",
    )
    is_synthetic: bool = Field(
        default=False, description="Whether the record is synthetic"
    )
    last_updated_at: Optional[datetime] = Field(
        default=None, description="When the record was last updated"
    )

    @field_validator("data_origin")
    @classmethod
    def _validate_data_origin(cls, value: str) -> str:
        if value.lower() not in DATA_ORIGINS:
            raise ValueError(
                f"data_origin must be one of {sorted(DATA_ORIGINS)}, got {value!r}"
            )
        return value.lower()

    @field_validator("verification_status")
    @classmethod
    def _validate_verification_status(cls, value: str) -> str:
        if value.lower() not in VERIFICATION_STATUSES:
            raise ValueError(
                f"verification_status must be one of {sorted(VERIFICATION_STATUSES)}, got {value!r}"
            )
        return value.lower()

    @field_validator("image_urls")
    @classmethod
    def _validate_image_urls(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is not None:
            for url in value:
                if not url or not isinstance(url, str):
                    raise ValueError("each image_url must be a non-empty string")
        return value

    @field_validator("delivery_days", "inventory_quantity", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        return int(value)

    @field_validator("delivery_days", "inventory_quantity")
    @classmethod
    def _validate_non_negative_int(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("quantity must be non-negative")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: Any) -> Optional[Decimal]:
        return _to_decimal(value)

    @field_validator("price")
    @classmethod
    def _validate_price_non_negative(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is not None and value < 0:
            raise ValueError("price must be non-negative")
        return value

    @field_validator("currency")
    @classmethod
    def _validate_currency_code(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("currency must be a 3-letter uppercase ISO 4217 code")
        return value

    @model_validator(mode="after")
    def _validate_synthetic_not_verified(self) -> "Product":
        """Synthetic records must never be presented as verified business data."""
        if self.is_synthetic and self.verification_status == "verified":
            raise ValueError(
                "Synthetic records must not be marked as verified"
            )
        return self
