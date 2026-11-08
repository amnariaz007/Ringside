from core import normalize


def test_address_variants_share_a_key():
    a = normalize.address_key("12 Main Street", "Apt. 4", "Newark", "07114", "us")
    b = normalize.address_key("12 main st", "apt 4", "NEWARK", "07 114", "US")
    assert a == b


def test_different_addresses_differ():
    assert normalize.address_key("12 Main St", "", "Newark", "07114", "US") != \
        normalize.address_key("14 Main St", "", "Newark", "07114", "US")


def test_email_stem_catches_numbered_accounts():
    stems = {normalize.email_stem(e) for e in
             ["sana.m1@inboxly.example", "sanam.2@inboxly.example", "Sana_M3+promo@Inboxly.example"]}
    assert stems == {"sanam@inboxly.example"}


def test_email_hash_is_case_insensitive_and_not_plaintext():
    h = normalize.hash_email("Ali@Example.com")
    assert h == normalize.hash_email("ali@example.com ")
    assert "ali" not in h


def test_phone_hash_ignores_formatting_and_empty():
    assert normalize.hash_phone("+1 (201) 555-0101") == normalize.hash_phone("12015550101")
    assert normalize.hash_phone("") == ""
