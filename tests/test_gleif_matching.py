from services.live_osint import rank_gleif_candidates


def _record(lei, name, country, status="ACTIVE"):
    return {
        "id": lei,
        "attributes": {
            "entity": {
                "legalName": {"name": name},
                "legalAddress": {"country": country},
                "status": status,
            }
        },
    }


def test_alphabet_exact_name_wins_over_similarly_named_entities():
    records = [
        _record("1", "ALPHABET ENERGY INC", "IN"),
        _record("2", "ALPHABET INC.", "US"),
        _record("3", "ALPHABET MINERALS INC", "IN"),
    ]
    result = rank_gleif_candidates("Alphabet Inc.", records)
    assert result["id"] == "2"
    assert result["match_type"] == "exact"
    assert result["match_score"] == 1.0


def test_google_llc_wins_over_google_subsidiaries():
    records = [
        _record("1", "GOOGLE FRANCE", "FR"),
        _record("2", "GOOGLE LLC", "US"),
        _record("3", "GOOGLE PAYMENT LIMITED", "GB"),
    ]
    result = rank_gleif_candidates("Google LLC", records)
    assert result["id"] == "2"
    assert result["match_type"] == "exact"


def test_legal_suffixes_are_normalized():
    records = [_record("1", "MICROSOFT CORPORATION", "US")]
    result = rank_gleif_candidates("Microsoft Corp", records)
    assert result["id"] == "1"
    assert result["match_type"] == "normalized"


def test_legal_form_disambiguates_parent_from_subsidiary():
    records = [
        _record("1", "Microsoft", "BE"),
        _record("2", "MICROSOFT CORPORATION", "US"),
        _record("3", "Microsoft India Corporation", "US"),
    ]
    result = rank_gleif_candidates("Microsoft Corp", records)
    assert result["id"] == "2"
    assert result["ambiguous"] is False


def test_similar_subdivisions_are_ambiguous_without_country():
    records = [
        _record("1", "Tata Consultancy Services Limited", "NO"),
        _record("2", "TATA CONSULTANCY SERVICES LIMITED", "IN"),
    ]
    result = rank_gleif_candidates("Tata Consultancy Services", records)
    assert result["ambiguous"] is True
    assert len(result["candidates"]) == 2


def test_country_disambiguates_similar_legal_entities():
    records = [
        _record("1", "Tata Consultancy Services Limited", "NO"),
        _record("2", "TATA CONSULTANCY SERVICES LIMITED", "IN"),
    ]
    result = rank_gleif_candidates(
        "Tata Consultancy Services", records, country="IN"
    )
    assert result["id"] == "2"
    assert result["ambiguous"] is False
