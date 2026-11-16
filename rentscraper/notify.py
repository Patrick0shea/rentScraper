"""Email the latest results (``python -m rentscraper.notify``).

Credentials come only from environment variables (GitHub Actions secrets),
never from files in the repository:

  SMTP_USERNAME   account to send from (e.g. a Gmail address)
  SMTP_PASSWORD   its password / app password (Gmail: an "App password")
  MAIL_TO         recipient(s), comma separated (defaults to SMTP_USERNAME)
  SMTP_HOST       default smtp.gmail.com
  SMTP_PORT       default 465 (SSL); 587 uses STARTTLS
  MAIL_FROM       default SMTP_USERNAME

If credentials are missing the email is skipped with a warning (exit 0), so
an unconfigured fork never fails its scheduled run.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

log = logging.getLogger("rentscraper.notify")

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """Escape, then render [links](url), **bold** and `code`."""
    out = html.escape(text, quote=False)
    out = _LINK_RE.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _CODE_RE.sub(r"<code>\1</code>", out)
    return out


def markdown_to_html(md: str) -> str:
    """Render the subset of Markdown produced by ``outputs.build_summary``."""
    parts: list[str] = []
    lines = md.splitlines()
    i = 0
    cell = "padding:4px 8px;border:1px solid #ddd;vertical-align:top;"
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i].strip().strip("|"))
                i += 1
            rows = [r for r in rows if not re.fullmatch(r"[\s:|-]+", r)]
            if rows:
                head, *body = rows
                t = ['<table style="border-collapse:collapse;font-size:13px;margin:8px 0;">']
                t.append("<tr>" + "".join(
                    f'<th style="{cell}background:#f3f3f3;text-align:left;">{_inline(c.strip())}</th>' for c in head.split("|")
                ) + "</tr>")
                for r in body:
                    t.append("<tr>" + "".join(f'<td style="{cell}">{_inline(c.strip())}</td>' for c in r.split("|")) + "</tr>")
                t.append("</table>")
                parts.append("".join(t))
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            parts.append("<ul>" + "".join(items) + "</ul>")
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            parts.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif line.strip():
            parts.append(f"<p>{_inline(line)}</p>")
        i += 1
    body = "\n".join(parts)
    return (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;'
        'color:#222;max-width:1100px;">' + body + "</body></html>"
    )


def build_subject(out_dir: Path) -> str:
    date = datetime.now(timezone.utc).strftime("%d %b %Y")
    try:
        report = json.loads((out_dir / "run_report.json").read_text(encoding="utf-8"))
        shortlist = json.loads((out_dir / "shortlist.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"Dublin rentals – {date}"
    three = sum(1 for x in shortlist if x.get("tier") == 1)
    two = sum(1 for x in shortlist if x.get("tier") == 2)
    new = sum(1 for x in shortlist if x.get("is_new"))
    return (
        f"Dublin rentals {date}: {len(shortlist)} matches ({three}× 3-bed, {two}× 2-bed), "
        f"{new} new, {report.get('price_changes', 0)} price changes"
    )


def build_message(out_dir: Path, sender: str, recipients: list[str], run_url: Optional[str] = None) -> EmailMessage:
    summary_path = out_dir / "summary.md"
    md = summary_path.read_text(encoding="utf-8")
    if run_url:
        md += f"\n\n[Workflow run and downloadable results]({run_url})\n"
    msg = EmailMessage()
    msg["Subject"] = build_subject(out_dir)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(md)
    msg.add_alternative(markdown_to_html(md), subtype="html")
    shortlist_csv = out_dir / "shortlist.csv"
    if shortlist_csv.is_file():
        msg.add_attachment(shortlist_csv.read_bytes(), maintype="text", subtype="csv", filename="shortlist.csv")
    return msg


def send(msg: EmailMessage, host: str, port: int, username: str, password: str, timeout: float = 30) -> None:
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as s:
            s.login(username, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as s:
            s.starttls(context=context)
            s.login(username, password)
            s.send_message(msg)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rentscraper.notify", description="Email the latest scraper results")
    p.add_argument("--output-dir", default=os.environ.get("RENTSCRAPER_OUTPUT_DIR", "output"))
    p.add_argument("--dry-run", action="store_true", help="build the email and print it instead of sending")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    out_dir = Path(args.output_dir)
    if not (out_dir / "summary.md").is_file():
        log.error("no summary.md in %s – run the scraper first", out_dir)
        return 1

    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipients = [r.strip() for r in (os.environ.get("MAIL_TO") or username).split(",") if r.strip()]
    sender = os.environ.get("MAIL_FROM", "").strip() or username
    run_url = None
    if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        run_url = f"{server}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    if args.dry_run:
        msg = build_message(out_dir, sender or "sender@example.invalid", recipients or ["recipient@example.invalid"], run_url)
        print(msg["Subject"])
        print(f"{len(msg.as_bytes())} bytes, parts: {[p.get_content_type() for p in msg.walk()]}")
        return 0
    if not (username and password and recipients):
        log.warning("email skipped: set SMTP_USERNAME, SMTP_PASSWORD and MAIL_TO secrets to enable it")
        return 0

    msg = build_message(out_dir, sender, recipients, run_url)
    host = os.environ.get("SMTP_HOST", "").strip() or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT", "").strip() or 465)
    try:
        send(msg, host, port, username, password)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("sending email via %s:%d failed: %s", host, port, exc)
        return 1
    log.info("emailed results to %d recipient(s): %s", len(recipients), msg["Subject"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
