from foxengine.services.format_detect import (
    _sniff_csv,
    analyze_text_payload,
    is_delimited_text_filename,
)


def test_is_delimited_text_filename() -> None:
    assert is_delimited_text_filename("data.csv")
    assert is_delimited_text_filename("notes.TXT")
    assert is_delimited_text_filename("sheet.tsv")
    assert not is_delimited_text_filename("data.jsonl")


def test_sniff_csv_semicolon() -> None:
    text = "email;password\na@x.com;secret\nb@y.com;pass2\n"
    delim, headers, score = _sniff_csv(text)
    assert delim == ";"
    assert headers == ["email", "password"]
    assert score >= 0.75


def test_analyze_text_payload_autodetects_txt_delimiter() -> None:
    payload = b"name|email\nAlice|a@example.com\n"
    result = analyze_text_payload("leads.txt", payload)
    assert result.format == "csv"
    assert result.csv_delimiter == "|"
    assert result.headers == ["name", "email"]


def test_analyze_text_payload_delimiter_override() -> None:
    payload = b"email;password\na@x.com;secret\n"
    auto = analyze_text_payload("data.txt", payload)
    assert auto.csv_delimiter == ";"

    forced = analyze_text_payload("data.txt", payload, csv_delimiter=",")
    assert forced.format == "csv"
    assert forced.csv_delimiter == ","
    assert forced.headers == ["email;password"]
