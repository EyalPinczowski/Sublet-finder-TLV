from src.contact import whatsapp_link


def test_whatsapp_link_normalizes_a_dashed_mobile_number():
    assert whatsapp_link("050-1234567") == "https://wa.me/972501234567"


def test_whatsapp_link_none_without_a_phone():
    assert whatsapp_link(None) is None
    assert whatsapp_link("") is None


def test_whatsapp_link_none_for_a_non_mobile_number():
    assert whatsapp_link("03-1234567") is None  # landline, not 05X


def test_whatsapp_link_includes_a_pre_filled_message_when_given():
    link = whatsapp_link("050-1234567", message="מה המחיר?")
    assert link.startswith("https://wa.me/972501234567?text=")
    assert "%D7%9E%D7%94" in link  # percent-encoded Hebrew, not raw text


def test_whatsapp_link_plain_without_a_message():
    link = whatsapp_link("050-1234567")
    assert "?text=" not in link
