from helpers.hello import hello


def test_hello_default() -> None:
    assert hello() == "Hello, World!"


def test_hello_with_name() -> None:
    assert hello("Max Mustermann") == "Hello, Max Mustermann!"


def test_hello_strips_whitespace() -> None:
    assert hello("  Max  ") == "Hello, Max!"


def test_hello_blank_name_uses_default() -> None:
    assert hello("   ") == "Hello, World!"
