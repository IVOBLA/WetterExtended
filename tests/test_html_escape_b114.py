"""B114: HTML-Escaping im AI-Report verhindert XSS durch LLM-Inhalt."""
from html import escape


def test_b114_title_escaped():
    """Script-Tags im Titel müssen escaped werden."""
    raw = '<script>alert(1)</script>'
    escaped = escape(raw)
    assert '<script>' not in escaped
    assert '&lt;script&gt;' in escaped


def test_b114_normal_text_unchanged():
    """Normaler Text wird durch escape nicht verändert."""
    raw = "Gewitterzelle Typ A, Intensität hoch"
    assert escape(raw) == raw


def test_b114_quotes_escaped():
    """Anführungszeichen werden escaped."""
    raw = 'He said "hello" & goodbye'
    escaped = escape(raw)
    assert '"' not in escaped or '&quot;' in escaped or '&#x27;' in escaped


def test_b114_ai_report_suggestion_fields_are_escaped(monkeypatch):
    """AI-Report-Mail rendert LLM-Felder nur HTML-escaped."""
    import email_notifier

    captured = {}

    def fake_send_smtp(recipients, subject, html_body):
        captured["recipients"] = recipients
        captured["subject"] = subject
        captured["html"] = html_body
        return True

    monkeypatch.setattr(email_notifier, "_SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(email_notifier, "_SMTP_USER", "user@example.test")
    monkeypatch.setattr(email_notifier, "_SMTP_PASS", "secret")
    monkeypatch.setattr(email_notifier, "_send_smtp", fake_send_smtp)

    result = {
        "overall_status": "ok",
        "suggestions": [
            {
                "priority": "<high>",
                "title": "<script>alert(1)</script>",
                "description": "Beschreibung <b>fett</b>",
                "action": "Nutze A & B",
            }
        ],
        "report_snapshot": {"generated_utc": "2026-06-09T00:00:00Z"},
    }

    assert email_notifier.send_ai_report_email(result, "ops@example.test") is True
    html = captured["html"]
    assert "<script>" not in html
    assert "<b>fett</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Beschreibung &lt;b&gt;fett&lt;/b&gt;" in html
    assert "Nutze A &amp; B" in html
    assert "&lt;HIGH&gt;" in html
