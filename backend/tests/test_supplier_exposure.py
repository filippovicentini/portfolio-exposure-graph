from uuid import UUID, uuid4

from app.domain.enums import CandidateRole
from app.domain.models import DependencyExposureRow
from app.services.graph_service import aggregate_supplier_exposure

NVDA = ("0001045810", "NVIDIA CORP")
AAPL = ("0000320193", "Apple Inc.")


def row(asset_path, company, supplier_id, supplier_name, roles, weight):
    return DependencyExposureRow(
        asset_path=asset_path,
        company_cik=company[0],
        company_name=company[1],
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        roles=roles,
        company_path_weight_pct=weight,
    )


def scenario_rows():
    """NVDA 60% direct; QQQ 40% holding NVDA at 6% (2.4) and AAPL at 9% (3.6)."""
    return [
        row(["NVDA"], NVDA, "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 60.0),
        row(["NVDA"], NVDA, "supplier:samsung", "Samsung", [CandidateRole.MEMORY_SUPPLIER], 60.0),
        row(["QQQ", "NVDA"], NVDA, "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 2.4),
        row(["QQQ", "NVDA"], NVDA, "supplier:samsung", "Samsung", [CandidateRole.MEMORY_SUPPLIER], 2.4),
        row(["QQQ", "AAPL"], AAPL, "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 3.6),
        row(
            ["QQQ", "AAPL"],
            AAPL,
            "supplier:foxconn",
            "Foxconn",
            [CandidateRole.CONTRACT_MANUFACTURER],
            3.6,
        ),
    ]


def by_supplier(result):
    return {item.supplier_id: item for item in result.suppliers}


def by_role(result):
    return {item.role: item for item in result.roles}


def test_supplier_weight_sums_every_route_to_every_dependent_company():
    result = aggregate_supplier_exposure(uuid4(), scenario_rows())

    tsmc = by_supplier(result)["supplier:tsmc"]
    assert tsmc.weight_pct == 66.0  # 60 direct NVDA + 2.4 NVDA via QQQ + 3.6 AAPL
    assert [(c.company_name, c.weight_pct) for c in tsmc.companies] == [
        ("NVIDIA CORP", 62.4),
        ("Apple Inc.", 3.6),
    ]
    assert tsmc.roles == [CandidateRole.FOUNDRY]
    assert by_supplier(result)["supplier:samsung"].weight_pct == 62.4
    assert by_supplier(result)["supplier:foxconn"].weight_pct == 3.6


def test_suppliers_and_roles_are_sorted_by_weight():
    result = aggregate_supplier_exposure(uuid4(), scenario_rows())

    assert [item.supplier_name for item in result.suppliers] == [
        "TSMC",
        "Samsung",
        "Foxconn",
    ]
    assert [item.role for item in result.roles] == [
        CandidateRole.FOUNDRY,
        CandidateRole.MEMORY_SUPPLIER,
        CandidateRole.CONTRACT_MANUFACTURER,
    ]


def test_coverage_counts_each_route_once_while_suppliers_overlap():
    result = aggregate_supplier_exposure(uuid4(), scenario_rows())

    # Routes: NVDA direct 60, NVDA via QQQ 2.4, AAPL via QQQ 3.6.
    assert result.dependency_coverage_pct == 66.0
    # Supplier weights overlap: NVDA counts for both TSMC and Samsung.
    assert sum(item.weight_pct for item in result.suppliers) == 132.0
    assert "more than 100%" in result.overlap_basis
    assert "no numeric supplier impact" in result.dependency_basis


def test_role_counts_a_route_once_even_with_several_suppliers_in_that_role():
    rows = scenario_rows() + [
        row(["QQQ", "AAPL"], AAPL, "supplier:intel", "Intel", [CandidateRole.FOUNDRY], 3.6)
    ]

    result = aggregate_supplier_exposure(uuid4(), rows)

    foundry = by_role(result)[CandidateRole.FOUNDRY]
    assert foundry.weight_pct == 66.0  # AAPL's route is not counted twice
    assert foundry.supplier_count == 2
    assert by_supplier(result)["supplier:intel"].weight_pct == 3.6


def test_supplier_with_several_roles_lists_each_role_once():
    rows = [
        row(
            ["NVDA"],
            NVDA,
            "supplier:tsmc",
            "TSMC",
            [CandidateRole.FOUNDRY, CandidateRole.MANUFACTURING_PARTNER],
            60.0,
        ),
        row(["MSFT"], ("0000789019", "MICROSOFT CORP"), "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 10.0),
    ]

    result = aggregate_supplier_exposure(uuid4(), rows)

    tsmc = by_supplier(result)["supplier:tsmc"]
    assert tsmc.weight_pct == 70.0
    assert tsmc.roles == [CandidateRole.FOUNDRY, CandidateRole.MANUFACTURING_PARTNER]
    assert by_role(result)[CandidateRole.MANUFACTURING_PARTNER].weight_pct == 60.0


def test_duplicate_rows_for_the_same_route_are_not_double_counted():
    rows = scenario_rows()
    rows.append(rows[0])

    result = aggregate_supplier_exposure(uuid4(), rows)

    assert by_supplier(result)["supplier:tsmc"].weight_pct == 66.0
    assert result.dependency_coverage_pct == 66.0


def test_no_dependencies_gives_an_empty_breakdown():
    portfolio_id = uuid4()

    result = aggregate_supplier_exposure(portfolio_id, [])

    assert result.portfolio_id == portfolio_id
    assert result.suppliers == []
    assert result.roles == []
    assert result.dependency_coverage_pct == 0.0


def test_floating_point_noise_is_rounded():
    rows = [
        row(["QQQ", "NVDA"], NVDA, "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 0.1),
        row(["XLK", "NVDA"], NVDA, "supplier:tsmc", "TSMC", [CandidateRole.FOUNDRY], 0.2),
    ]

    result = aggregate_supplier_exposure(UUID(int=1), rows)

    assert result.suppliers[0].weight_pct == 0.3
