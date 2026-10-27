from qrlabel.domain.models import LabelElement
from qrlabel.services.profile_rules import template_fields, template_issues, validate_profile


def test_older_profiles_allow_every_label(profile):
    profile.template_ids = []
    assert profile.allows_template("anything")


def test_allowed_list(profile):
    profile.template_ids = ["a", "b"]
    assert profile.allows_template("a") and not profile.allows_template("c")


def test_default_must_be_ticked(profile):
    profile.template_ids = ["a"]
    profile.template_id = "b"
    assert any("default label must be one of" in i for i in validate_profile(profile))
    profile.template_id = "a"
    assert not any("default label" in i for i in validate_profile(profile, template_ids={"a"}))


def test_deleted_ticked_label_reported(profile):
    profile.template_ids = ["a", "gone"]
    profile.template_id = "a"
    assert any("no longer exist" in i for i in validate_profile(profile, template_ids={"a"}))


def test_template_fields_and_issues(profile, template):
    template.elements.append(LabelElement(kind="text", x_mm=1, y_mm=1, w_mm=5, h_mm=3, text="Voucher {VOUCHER}"))
    template.elements.append(LabelElement(kind="text", x_mm=1, y_mm=5, w_mm=5, h_mm=3, field="ITEMID"))
    assert template_fields(template) == {"ASSETID", "VOUCHER", "ITEMID"}
    issues = template_issues(template, profile)
    assert issues and "ITEMID, VOUCHER" in issues[0]


def test_matching_template_has_no_issues(profile, template):
    assert template_issues(template, profile) == []


def test_qr_without_qr_fields_warns(profile, template):
    profile.qr.fields = []
    assert any("no QR fields" in i for i in template_issues(template, profile))


def test_profile_roundtrip_keeps_template_ids(profile):
    from qrlabel.domain.models import DataProfile

    profile.template_ids = ["a", "b"]
    assert DataProfile.from_dict(profile.to_dict()).template_ids == ["a", "b"]
