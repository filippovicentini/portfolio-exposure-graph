import pytest

from app.domain.enums import SupplierCompanyLinkStatus
from app.domain.models import CompanyResolution, SupplierIdentity
from app.services.supplier_company_linker import (
    SupplierCompanyLinker,
    is_linkable_alias,
    normalize_entity_name,
)

# Registrant names exactly as the SEC company directory spells them.
SEC_DIRECTORY = [
    CompanyResolution(ticker="TSM", cik="0001046179", name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"),
    CompanyResolution(ticker="SKHY", cik="0002120882", name="SK hynix Inc."),
    CompanyResolution(ticker="MU", cik="0000723125", name="MICRON TECHNOLOGY INC"),
    CompanyResolution(ticker="FN", cik="0001408710", name="Fabrinet"),
    CompanyResolution(ticker="NVDA", cik="0001045810", name="NVIDIA CORP"),
]


def supplier(supplier_id, canonical_name, *aliases):
    return SupplierIdentity(
        supplier_id=supplier_id,
        canonical_name=canonical_name,
        aliases=[canonical_name, *aliases],
    )


@pytest.mark.parametrize(
    ("filing_name", "sec_name"),
    [
        ("Taiwan Semiconductor Manufacturing Company Limited", "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"),
        ("Micron Technology, Inc.", "MICRON TECHNOLOGY INC"),
        ("SK Hynix Inc.", "SK hynix Inc."),
        ("ASML Holding N.V.", "ASML HOLDING NV"),
        ("AT&T Inc.", "AT&T INC."),
        ("The Coca-Cola Company", "COCA COLA CO"),
    ],
)
def test_filing_and_registrant_spellings_normalize_equal(filing_name, sec_name):
    assert normalize_entity_name(filing_name) == normalize_entity_name(sec_name)


def test_only_trailing_legal_words_are_removed():
    assert normalize_entity_name("Company Holdings Corp") == "company holdings"
    assert normalize_entity_name("Limited Brands Inc") == "limited brands"
    # A name that is only a legal word is kept rather than emptied.
    assert normalize_entity_name("Company") == "company"


def test_short_acronyms_are_not_linkable_aliases():
    assert not is_linkable_alias("TSMC")
    assert not is_linkable_alias("AMD")
    assert is_linkable_alias("Samsung")
    assert is_linkable_alias("Micron Technology")


def test_nvidia_10k_suppliers_link_only_when_sec_registered():
    """The seven suppliers named in NVIDIA's FY2026 10-K."""
    linker = SupplierCompanyLinker(SEC_DIRECTORY, source_url="https://www.sec.gov/files/x.json")
    suppliers = [
        supplier("s:tsmc", "Taiwan Semiconductor Manufacturing Company Limited", "TSMC"),
        supplier("s:samsung", "Samsung Electronics Co., Ltd.", "Samsung"),
        supplier("s:hynix", "SK Hynix Inc."),
        supplier("s:micron", "Micron Technology, Inc."),
        supplier("s:honhai", "Hon Hai Precision Industry Co., Ltd."),
        supplier("s:wistron", "Wistron Corporation"),
        supplier("s:fabrinet", "Fabrinet"),
    ]

    links = {item.supplier_id: linker.link(item) for item in suppliers}

    linked = {
        supplier_id: link.company_cik
        for supplier_id, link in links.items()
        if link.status == SupplierCompanyLinkStatus.LINKED
    }
    assert linked == {
        "s:tsmc": "0001046179",
        "s:hynix": "0002120882",
        "s:micron": "0000723125",
        "s:fabrinet": "0001408710",
    }
    for supplier_id in ("s:samsung", "s:honhai", "s:wistron"):
        assert links[supplier_id].status == SupplierCompanyLinkStatus.UNMATCHED
        assert links[supplier_id].company_cik is None

    tsmc = links["s:tsmc"]
    assert tsmc.company_name == "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"
    assert tsmc.matched_name == "Taiwan Semiconductor Manufacturing Company Limited"
    assert tsmc.method == "sec_directory_normalized_exact_v1"
    assert tsmc.source_url == "https://www.sec.gov/files/x.json"


def test_an_acronym_alias_never_creates_a_link():
    directory = SEC_DIRECTORY + [
        CompanyResolution(ticker="TSMX", cik="0009999999", name="TSMC Inc")
    ]
    linker = SupplierCompanyLinker(directory)

    link = linker.link(supplier("s:x", "Some Foundry Partner", "TSMC"))

    assert link.status == SupplierCompanyLinkStatus.UNMATCHED


def test_a_full_alias_can_link_when_the_canonical_name_does_not():
    linker = SupplierCompanyLinker(SEC_DIRECTORY)

    link = linker.link(supplier("s:mu", "Micron", "Micron Technology, Inc."))

    assert link.status == SupplierCompanyLinkStatus.LINKED
    assert link.company_cik == "0000723125"
    assert link.matched_name == "Micron Technology, Inc."


def test_names_pointing_at_several_ciks_are_ambiguous():
    directory = [
        CompanyResolution(ticker="AAA", cik="0000000001", name="Acme Holdings Inc"),
        CompanyResolution(ticker="BBB", cik="0000000002", name="ACME HOLDINGS CORP"),
    ]
    linker = SupplierCompanyLinker(directory)

    link = linker.link(supplier("s:acme", "Acme Holdings Ltd."))

    assert link.status == SupplierCompanyLinkStatus.AMBIGUOUS
    assert link.company_cik is None
    assert link.candidate_ciks == ["0000000001", "0000000002"]


def test_same_cik_reached_by_several_names_is_one_link():
    linker = SupplierCompanyLinker(SEC_DIRECTORY)

    link = linker.link(
        supplier(
            "s:tsmc",
            "Taiwan Semiconductor Manufacturing Company Limited",
            "Taiwan Semiconductor Manufacturing Co., Ltd.",
        )
    )

    assert link.status == SupplierCompanyLinkStatus.LINKED
    assert link.candidate_ciks == ["0001046179"]
