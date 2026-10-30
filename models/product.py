"""Preliminary Pydantic product model for the GRAN EU dataset.

Clearly separates mandatory product identifiers from optional business
information. Genuinely unavailable optional fields may be null.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Product(BaseModel):
    """A GRANIT EU product record.

    Mandatory identifiers:
        - article_number
        - product_name
        - data_origin

    Optional business information may be null when unavailable.
    """

    # --- Mandatory product identifiers ---
    article_number: str = Field(..., min_length=1, description="Unique article number")
    product_name: str = Field(..., min_length=1, description="Human readable product name")
    data_origin: str = Field(..., min_length=1, description="Source the product data originated from")

    verification_status: str = Field(
        default="unverified",
        description="Verification status of the product record",
    )

    # --- Optional business information ---
    brand: Optional[str] = Field(default=None)
    manufacturer: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    ean_gtin: Optional[str] = Field(default=None, description="EAN / GTIN barcode")
    description: Optional[str] = Field(default=None)
    country: Optional[str] = Field(default=None)
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code")
    price: Optional[float] = Field(default=None, description="Product price")
    vat_rate: Optional[float] = Field(default=None, description="VAT rate in percent (0-100)")
    specifications: Optional[dict[str, Any]] = Field(default=None)
    compatibility: Optional[str] = Field(default=None)
    compliance: Optional[str] = Field(default=None)
    inventory: Optional[dict[str, Any]] = Field(default=None)
    logistics: Optional[dict[str, Any]] = Field(default=None)
    product_url: Optional[str] = Field(default=None, description="Canonical product page URL")
    image_url: Optional[str] = Field(default=None, description="Product image URL")
    is_synthetic: bool = Field(default=False, description="Whether the record is synthetic")
    created_at: Optional[datetime] = Field(default=None)

    @field_validator("price")
    @classmethod
    def _price_non_negative(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("price must be non-negative")
        return value

    @field_validator("vat_rate")
    @classmethod
    def _vat_rate_range(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not (0 <= value <= 100):
            raise ValueError("vat_rate must be between 0 and 100")
        return value

    @field_validator("verification_status")
    @classmethod
    def _verification_status_values(cls, value: str) -> str:
        allowed = {"unverified", "verified", "rejected"}
        if value.lower() not in allowed:
            raise ValueError(f"verification_status must be one of {sorted(allowed)}")
        return value.lower()
