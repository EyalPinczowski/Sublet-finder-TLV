from src.contact import whatsapp_link


def test_whatsapp_link_normalizes_a_dashed_mobile_number():
    assert whatsapp_link("050-1234567") == "https://wa.me/972501234567"


def test_whatsapp_link_none_without_a_phone():
    assert whatsapp_link(None) is None
    assert whatsapp_link("") is None


def test_whatsapp_link_none_for_a_non_mobile_number():
    assert whatsapp_link("03-1234567") is None  # landline, not 05X


def test_whatsapp_link_keeps_a_non_israeli_international_number():
    # A "+"-prefixed number already carries its own country code — used
    # as-is rather than forced into the Israeli 972+05X shape.
    assert whatsapp_link("+1 619 375 2500") == "https://wa.me/16193752500"


def test_whatsapp_link_none_for_a_bare_number_without_a_plus():
    # No "+" and not a recognized Israeli mobile shape — nothing safe to
    # guess a country code for.
    assert whatsapp_link("619 375 2500") is None


def test_whatsapp_link_includes_a_pre_filled_message_when_given():
    link = whatsapp_link("050-1234567", message="מה המחיר?")
    assert link.startswith("https://wa.me/972501234567?text=")
    assert "%D7%9E%D7%94" in link  # percent-encoded Hebrew, not raw text


def test_whatsapp_link_plain_without_a_message():
    link = whatsapp_link("050-1234567")
    assert "?text=" not in link
