"""Seed data created on first run.

Known facts (from the business): source table AssetTable, QR = AssetId,
AssetId printed under the QR, sticker labels.
SAMPLE values (not yet confirmed): label 40 x 30 mm, gap 2 mm. Change them in the
Label Designer once the real sticker size is measured.
"""
from __future__ import annotations

from ..domain.models import DataProfile, FieldDef, LabelElement, LabelTemplate, QrConfig

DEFAULT_PROFILE_ID = "asset"
DEFAULT_TEMPLATE_ID = "asset-qr-sample-40x30"


def default_asset_profile() -> DataProfile:
    return DataProfile(
        id=DEFAULT_PROFILE_ID,
        name="Asset (AssetTable)",
        source="AssetTable",
        schema="dbo",
        dataarea_column="DATAAREAID",
        fields=[
            FieldDef(column="ASSETID", alias="Fixed asset number", searchable=True, display=True, required=True),
            FieldDef(column="NAME", alias="Name", searchable=True, display=True),
            FieldDef(column="TECHINFO1", alias="PU No.", searchable=True, display=True),
            FieldDef(column="TECHINFO2", alias="PO No.", searchable=True, display=True),
            FieldDef(column="CREATEDDATE", alias="Created date", data_type="date", display=True, range_search=True, fmt="%d/%m/%Y"),
        ],
        order_by=["ASSETID"],
        row_limit=200,
        qr=QrConfig(format="plain", fields=["ASSETID"], error_correction="M", max_bytes=100),
        template_id=DEFAULT_TEMPLATE_ID,
    )


def default_asset_template() -> LabelTemplate:
    return LabelTemplate(
        id=DEFAULT_TEMPLATE_ID,
        name="SAMPLE 40x30 mm - QR + Asset ID",
        width_mm=40.0,
        height_mm=30.0,
        gap_mm=2.0,
        media="gap",
        margin_mm=1.0,
        density=8,
        speed=4,
        qr_mode="bitmap",
        text_mode="bitmap",
        elements=[
            LabelElement(kind="qr", name="QR AssetId", x_mm=10.0, y_mm=2.0, w_mm=20.0, h_mm=20.0),
            LabelElement(
                kind="text", name="AssetId text", field="ASSETID",
                x_mm=1.5, y_mm=23.0, w_mm=37.0, h_mm=5.5, font_mm=3.4, bold=True, align="center",
            ),
        ],
    )
