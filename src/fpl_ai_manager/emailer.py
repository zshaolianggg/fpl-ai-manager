from __future__ import annotations
import html, os, re, smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid


def _inline(t):
    t=html.escape(str(t))
    t=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",t)
    t=re.sub(r"`(.+?)`",r"<code>\1</code>",t)
    return t


def _md(body):
    # Flat HTML only: deliberately no <details>, accordions or hidden sections.
    out=[]; mode=None
    def close():
        nonlocal mode
        if mode: out.append(f"</{mode}>"); mode=None
    for raw in body.splitlines():
        s=raw.strip()
        if not s: close(); continue
        if s.startswith("# "): close(); out.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s.startswith("## "): close(); out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("### "): close(); out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif re.match(r"^[-*]\s+",s):
            if mode!="ul": close(); out.append("<ul>"); mode="ul"
            out.append(f"<li>{_inline(re.sub(r'^[-*]\s+','',s))}</li>")
        elif re.match(r"^\d+[.)]\s+",s):
            if mode!="ol": close(); out.append("<ol>"); mode="ol"
            out.append(f"<li>{_inline(re.sub(r'^\d+[.)]\s+','',s))}</li>")
        else: close(); out.append(f"<p>{_inline(s)}</p>")
    close()
    return "\n".join(out)


def html_body(body, generated_at=None):
    stamp=generated_at or datetime.now(timezone.utc)
    run_marker=stamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""<!doctype html><html><body style="background:#f4f6f8;font-family:Arial,sans-serif;color:#17202a;line-height:1.55">
<div style="max-width:800px;margin:auto;background:white;padding:28px;border-radius:12px">
<style>h1{{font-size:26px}}h2{{font-size:20px;border-bottom:1px solid #eee;padding-bottom:6px;margin-top:26px;display:block!important}}
h3{{font-size:16px;background:#f6f8fa;padding:8px 10px;border-radius:6px;margin-top:18px;display:block!important}}
ul,ol,p{{display:block!important}}li{{margin:5px 0}}code{{background:#f2f4f5;padding:2px 5px;border-radius:4px}}</style>
<div style="font-size:11px;color:#7b8794;margin-bottom:10px">Generated {run_marker}</div>
{_md(body)}</div></body></html>"""


def _unique_subject(subject, now):
    enabled=os.getenv("EMAIL_UNIQUE_SUBJECTS","true").lower() in {"1","true","yes","on"}
    if not enabled:
        return subject
    # Repeated preview runs with identical subjects are commonly grouped by mail
    # clients, which can collapse repeated content behind an expand control.
    # A run timestamp keeps each recommendation as a standalone message.
    return f"{subject} - {now.strftime('%Y-%m-%d %H:%M UTC')}"


def send_email(subject,body,attachments=None):
    now=datetime.now(timezone.utc)
    msg=EmailMessage(); msg["Subject"]=_unique_subject(subject,now); msg["From"]=os.environ["EMAIL_FROM"]; msg["To"]=os.environ["EMAIL_TO"]
    msg["Date"]=format_datetime(now); msg["Message-ID"]=make_msgid(domain=os.getenv("EMAIL_MESSAGE_ID_DOMAIN") or None)
    msg["X-FPL-Run-ID"]=now.strftime("%Y%m%dT%H%M%S%fZ")
    msg.set_content(body); msg.add_alternative(html_body(body,now),subtype="html")
    for filename,content,mimetype in attachments or []:
        maintype,subtype=mimetype.split("/",1)
        payload=content.encode() if isinstance(content,str) else content
        msg.add_attachment(payload,maintype=maintype,subtype=subtype,filename=filename)
    host=os.environ["SMTP_HOST"]; port=int(os.getenv("SMTP_PORT","587"))
    with smtplib.SMTP(host,port,timeout=30) as s:
        if os.getenv("SMTP_USE_TLS","true").lower() in {"1","true","yes"}: s.starttls()
        if os.getenv("SMTP_USERNAME"): s.login(os.environ["SMTP_USERNAME"],os.getenv("SMTP_PASSWORD",""))
        s.send_message(msg)
