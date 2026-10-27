"""Seed data created on first run.

Known facts (from the business): source table AssetTable, QR = AssetId,
AssetId printed under the QR, sticker labels.
SAMPLE values (not yet confirmed): label 40 x 30 mm, gap 2 mm. Change them in the
Label Designer once the real sticker size is measured.
"""
from __future__ import annotations

from ..domain.models import DataProfile, FieldDef, LabelElement, LabelTemplate, LookupDef, QrConfig

DEFAULT_PROFILE_ID = "asset"
DEFAULT_TEMPLATE_ID = "asset-qr-sample-40x30"


def bundled_templates() -> tuple[list[LabelTemplate], str]:
    """Label templates shipped with the app (resources/templates) and the id of the default one.

    To change them: export the template from the Label Designer, replace the JSON file
    in src/qrlabel/resources/templates, update index.json and rebuild the installer.
    """
    import json
    import logging

    from ..services.template_io import read_template_file
    from .paths import resource_path

    folder = resource_path("templates")
    index_file = folder / "index.json"
    if not index_file.exists():
        return [], ""
    try:
        index = json.loads(index_file.read_text(encoding="utf-8"))
        templates = [read_template_file(folder / name) for name in index.get("files", [])]
    except Exception:  # a broken bundle must not stop the app; fall back to the sample template
        logging.getLogger(__name__).exception("Cannot load bundled label templates")
        return [], ""
    ids = {t.id for t in templates}
    default = index.get("default") if index.get("default") in ids else (templates[0].id if templates else "")
    return templates, default


def default_asset_qr() -> QrConfig:
    """Same QR text as the previous application, e.g.

    Asset code : FA-IT-5-14-0020
    Name : Computer Set - Core i3 (NCR107 Office Mold)
    Acquisition date : 29/04/2014
    Acquisition : 9,600.00
    Department : FPRO_MOLD
    Purchase order :

    Error correction L keeps the QR scannable on small stickers (about 180-260 bytes of text).
    """
    return QrConfig(
        format="labeled",
        fields=["ASSETID", "NAME", "ACQUISITIONDATE", "ACQUISITIONPRICE", "DIMENSION", "PURCHID"],
        labels={
            "ASSETID": "Asset code", "NAME": "Name", "ACQUISITIONDATE": "Acquisition date",
            "ACQUISITIONPRICE": "Acquisition", "DIMENSION": "Department", "PURCHID": "Purchase order",
        },
        label_separator=" : ",
        line_separator="\r\n",
        null_policy="empty",  # only Asset code is required (field.required)
        error_correction="L",
        max_bytes=600,
    )


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
            # PO as in the previous application: AssetBook.PurchId; TechInfo2 when PurchId is empty
            FieldDef(column="PURCHID", alias="PO No.", table="ASSETBOOK", fallback="TECHINFO2", searchable=True, display=True),
            FieldDef(column="DIMENSION", alias="Department", table="ASSETBOOK", searchable=True, display=True),
            FieldDef(column="ACQUISITIONDATE", alias="Acquisition date", table="ASSETBOOK", data_type="date",
                     display=True, range_search=True, fmt="%d/%m/%Y"),
            FieldDef(column="ACQUISITIONPRICE", alias="Acquisition price", table="ASSETBOOK", data_type="decimal",
                     display=True, fmt=",2"),
            FieldDef(column="CREATEDDATE", alias="Created date", data_type="date", display=True, range_search=True, fmt="%d/%m/%Y"),
        ],
        # One AssetBook row per asset: the book with the acquisition price wins (some assets have
        # a second book with price 0), then by BookId.
        lookups=[LookupDef(table="ASSETBOOK", join=[["ASSETID", "ASSETID"], ["DATAAREAID", "DATAAREAID"]],
                           order_by=["ACQUISITIONPRICE DESC", "BOOKID"])],
        order_by=["ASSETID"],
        row_limit=200,
        qr=default_asset_qr(),
        template_id=DEFAULT_TEMPLATE_ID,
        template_ids=[DEFAULT_TEMPLATE_ID],
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


JOURNAL_PROFILE_ID = "inventjournal"
JOURNAL_SOURCES = ["INVENTJOURNALTRANS", "INVENTDIM", "INVENTTABLE", "INVENTTABLEMODULE"]
TRANSFER_JOURNAL_TYPE = "2"  # InventJournalType::Transfer (checked in AX: InventJournalTable type 2 = "Transfer journal")


def default_journal_profile(template_ids: list[str] | None = None) -> DataProfile:
    """Inventory transfer journal lines (STOCK label): one label per journal line.

    InventDim, InventTable and InventTableModule are shared by all companies through the AX
    virtual company (DB1 -> VIR), so they are joined with DATAAREAID = @VIRTUAL.
    """
    virtual = ["DATAAREAID", "@VIRTUAL"]
    dim = "INVENTDIM"

    def dim_field(column: str, alias: str, show: bool = True) -> FieldDef:
        return FieldDef(column=column, alias=alias, table=dim, display=show)

    template_ids = list(template_ids or [])
    return DataProfile(
        id=JOURNAL_PROFILE_ID,
        name="Inventory transfer journal",
        source="INVENTJOURNALTRANS",
        schema="dbo",
        dataarea_column="DATAAREAID",
        fields=[
            FieldDef(column="VOUCHER", alias="Voucher", searchable=True, search_mode="starts"),
            FieldDef(column="ITEMID", alias="Item number", searchable=True, search_mode="starts", required=True),
            FieldDef(column="ITEMNAME", alias="Item name", table="INVENTTABLE"),
            FieldDef(column="QTY", alias="Qty", data_type="decimal", fmt="abs"),  # transfer lines are negative
            FieldDef(column="UNITID", alias="Unit", table="INVENTTABLEMODULE"),
            dim_field("INVENTSIZEID", "Grade"),
            dim_field("INVENTBATCHID", "Batch No"),
            FieldDef(column="NOTES", alias="Note"),
            FieldDef(column="JOURNALID", alias="Journal", searchable=True, search_mode="starts"),
            FieldDef(column="LINENUM", alias="Line", data_type="decimal"),
            FieldDef(column="TRANSDATE", alias="Date", data_type="date", range_search=True, fmt="%d/%m/%Y"),
            dim_field("INVENTLOCATIONID", "Warehouse"),
            dim_field("WMSLOCATIONID", "Location"),
            dim_field("INVENTSERIALID", "Serial", show=False),
            dim_field("CONFIGID", "Configuration", show=False),
            dim_field("INVENTCOLORID", "Colour", show=False),
        ],
        lookups=[
            LookupDef(table=dim, join=[["INVENTDIMID", "INVENTDIMID"]], conditions=[virtual]),
            LookupDef(table="INVENTTABLE", join=[["ITEMID", "ITEMID"]], conditions=[virtual]),
            LookupDef(table="INVENTTABLEMODULE", join=[["ITEMID", "ITEMID"]],
                      conditions=[["MODULETYPE", "0"], virtual]),  # 0 = inventory unit
        ],
        filters=[["JOURNALTYPE", TRANSFER_JOURNAL_TYPE]],
        order_by=["TRANSDATE DESC", "JOURNALID DESC", "LINENUM"],  # Journal ids do not sort by time
        row_limit=500,
        require_criteria=True,  # about 1.3 million transfer lines in DB1
        qr=QrConfig(format="plain", fields=["ITEMID"], null_policy="empty", error_correction="M", max_bytes=300),
        template_id=template_ids[0] if template_ids else "",
        template_ids=template_ids,
    )
