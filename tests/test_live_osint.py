import os
from unittest.mock import patch

from core.models import RiskTier, SanctionStatus, VendorProfile
from services.live_osint import enrich_profile


def _profile() -> VendorProfile:
    return VendorProfile(
        vendor_id="VND-LIVE-1",
        company_name="Example Vendor Ltd",
        domain="example.com",
        country="",
        registration_number="",
        domain_age_years=5.0,
        credit_score=80,
        financial_rating="A",
        sanction_pep_status=SanctionStatus.CLEARED,
        past_litigation_count=0,
        compliance_certifications=["SOC 2 Type II"],
        risk_score=12.0,
        risk_tier=RiskTier.LOW,
    )


def test_live_osint_adds_registry_and_web_provenance():
    with patch.dict(
        os.environ,
        {"LIVE_OSINT_ENABLED": "true", "OSINT_CACHE_TTL_SECONDS": "0"},
    ), patch(
        "services.live_osint.gleif_lookup",
        return_value={
            "source": "GLEIF",
            "id": "549300TEST",
            "country": "US",
            "status": "ACTIVE",
            "url": "https://search.gleif.org/#/record/549300TEST",
        },
    ), patch(
        "services.live_osint.web_search",
        return_value=[
            {
                "title": "Example Vendor",
                "url": "https://example.com",
                "snippet": "Official site",
                "provider": "Tavily",
            }
        ],
    ):
        profile = enrich_profile(_profile(), "Example Vendor Ltd")

    assert profile.live_osint is True
    assert profile.registry_source == "GLEIF"
    assert profile.registry_id == "549300TEST"
    assert profile.web_sources
    assert any("Live registry match" in flag for flag in profile.flags)


def test_live_osint_can_be_disabled():
    with patch.dict(os.environ, {"LIVE_OSINT_ENABLED": "false"}):
        profile = enrich_profile(_profile(), "Example Vendor Ltd")
    assert profile.live_osint is False
    assert profile.web_sources == []
