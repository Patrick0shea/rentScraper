import json

import pytest

from rentscraper import notify

SUMMARY = """# Dublin rental search – results

Run: **2026-11-16** · Group of 3

## Best 3-bedroom properties

| Score | Property | Rent |
|---:|---|---:|
| 80 | [1 Test Road <b>](https://example.test/1) | €2,900 |

- Price note with `code`
"""


@pytest.fixture
def out(tmp_path):
    (tmp_path / "summary.md").write_text(SUMMARY, encoding="utf-8")
    (tmp_path / "shortlist.csv").write_text("score,url\n80,https://example.test/1\n", encoding="utf-8")
    (tmp_path / "shortlist.json").write_text(json.dumps([{"tier": 1, "is_new": True}, {"tier": 2, "is_new": False}]))
    (tmp_path / "run_report.json").write_text(json.dumps({"price_changes": 3}))
    return tmp_path


def test_markdown_to_html_renders_tables_links_and_escapes():
    h = notify.markdown_to_html(SUMMARY)
    assert "<h1>" in h and "<h2>Best 3-bedroom properties</h2>" in h
    assert '<a href="https://example.test/1">1 Test Road &lt;b&gt;</a>' in h
    assert h.count("<tr>") == 2  # header + 1 row, separator dropped
    assert "<strong>2026-11-16</strong>" in h and "<code>code</code>" in h and "<li>" in h


def test_subject_counts(out):
    s = notify.build_subject(out)
    assert "2 matches (1× 3-bed, 1× 2-bed), 1 new, 3 price changes" in s


def test_message_has_html_text_and_csv(out):
    msg = notify.build_message(out, "a@example.test", ["b@example.test"], "https://github.com/x/y/actions/runs/1")
    types = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in types and "text/html" in types and "text/csv" in types
    assert "actions/runs/1" in msg.get_body(("plain",)).get_content()


def test_skips_without_credentials(out, monkeypatch, caplog):
    for k in ("SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    assert notify.main(["--output-dir", str(out)]) == 0
    assert "email skipped" in caplog.text


def test_sends_with_ssl_by_default(out, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["to"] = msg["To"]

    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_TO", "one@example.test, two@example.test")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    assert notify.main(["--output-dir", str(out)]) == 0
    assert sent == {"host": "smtp.gmail.com", "port": 465, "login": ("sender@example.test", "app-password"),
                    "to": "one@example.test, two@example.test"}


def test_send_failure_returns_1(out, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", Boom)
    monkeypatch.setenv("SMTP_USERNAME", "s@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    assert notify.main(["--output-dir", str(out)]) == 1


def test_missing_summary_is_error(tmp_path):
    assert notify.main(["--output-dir", str(tmp_path)]) == 1
