
from __future__ import annotations
import html, os, re, smtplib
from email.message import EmailMessage

def _inline(t):
    t=html.escape(str(t))
    t=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",t)
    t=re.sub(r"`(.+?)`",r"<code>\1</code>",t)
    return t

def _md(body):
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

def html_body(body):
    return f"""<!doctype html><html><body style="background:#f4f6f8;font-family:Arial,sans-serif;color:#17202a;line-height:1.55">
<div style="max-width:800px;margin:auto;background:white;padding:28px;border-radius:12px">
<style>h1{{font-size:26px}}h2{{font-size:20px;border-bottom:1px solid #eee;padding-bottom:6px;margin-top:26px}}
h3{{font-size:16px;background:#f6f8fa;padding:8px 10px;border-radius:6px;margin-top:18px}}
li{{margin:5px 0}}code{{background:#f2f4f5;padding:2px 5px;border-radius:4px}}</style>{_md(body)}</div></body></html>"""

def send_email(subject,body,attachments=None):
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=os.environ["EMAIL_FROM"]; msg["To"]=os.environ["EMAIL_TO"]
    msg.set_content(body); msg.add_alternative(html_body(body),subtype="html")
    for filename,content,mimetype in attachments or []:
        maintype,subtype=mimetype.split("/",1)
        payload=content.encode() if isinstance(content,str) else content
        msg.add_attachment(payload,maintype=maintype,subtype=subtype,filename=filename)
    host=os.environ["SMTP_HOST"]; port=int(os.getenv("SMTP_PORT","587"))
    with smtplib.SMTP(host,port,timeout=30) as s:
        if os.getenv("SMTP_USE_TLS","true").lower() in {"1","true","yes"}: s.starttls()
        if os.getenv("SMTP_USERNAME"): s.login(os.environ["SMTP_USERNAME"],os.getenv("SMTP_PASSWORD",""))
        s.send_message(msg)
