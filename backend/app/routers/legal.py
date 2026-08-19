from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from datetime import datetime

router = APIRouter()

YEAR = datetime.now().year

STYLE = """\
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:#0a0a0f;color:#E6E8EB;line-height:1.8;-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;padding:40px 24px}
.logo{font-size:.95rem;font-weight:900;letter-spacing:.08em;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:28px;display:inline-block}
h1{font-size:clamp(1.5rem,3.5vw,2rem);font-weight:800;color:#E6E8EB;margin-bottom:4px;letter-spacing:-0.5px}
.sub{color:#9CA3AF;font-size:.85rem;margin-bottom:36px}
h2{font-size:1.05rem;font-weight:700;color:#E6E8EB;margin:28px 0 10px}
p,li{color:#E6E8EB;margin-bottom:8px;font-size:.88rem}
ul{padding-left:20px}
li{margin-bottom:4px}
a{color:#a5b4fc;text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:rgba(165,180,252,.2)}
.nav{margin-bottom:36px;display:flex;gap:20px;align-items:center;padding-bottom:24px;border-bottom:1px solid rgba(255,255,255,.06)}
.nav a{color:#9CA3AF;font-size:.8rem;font-weight:500;border-bottom:none}
.nav a.active{color:#a5b4fc}
.nav a:hover{color:#E6E8EB;border-bottom:none}
hr{border:none;border-top:1px solid rgba(255,255,255,.06);margin:36px 0}
.foot{color:#6B7280;font-size:.75rem}
code{color:#a5b4fc;font-size:.82rem}
address{font-style:normal;color:#E6E8EB;font-size:.88rem;margin-top:4px}
strong{color:#E6E8EB}
</style>"""

LOGO = """\
<div class="logo">AR</div>"""

def _nav(active: str) -> str:
    def link(href, label):
        cls = ' class="active"' if href == active else ""
        return f'<a href="{href}"{cls}>{label}</a>'
    return f"""\
<div class="nav">
{link("/privacy", "Privacy Policy")}
{link("/terms", "Terms of Service")}
    <a href="https://github.com/tirforge/Aruvi">Aruvi</a>
</div>"""

PAGE_TPL = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/aruvi-brand.png">
<title>{title} — Aruvi</title>{style}</head>
<body>
<div class="wrap">
{logo}
{nav}
{content}
<hr>
<p class="foot">Aruvi · {year}</p>
</div>
</body>
</html>"""

def page(title, content, active):
    return PAGE_TPL.format(
        title=title, style=STYLE, logo=LOGO, nav=_nav(active), content=content, year=YEAR
    )


PRIVACY_CONTENT = """\
<h1>Privacy Policy</h1>
<p class="sub">Last updated: July 27, 2026</p>

<p>This Privacy Policy describes how Aruvi ("we", "our", "us") collects, uses, and handles your information when you use our service.</p>

<h2>Information We Collect</h2>
<ul>
<li><strong>Telegram ID</strong> — used to identify your account and associate your files. Stored in our database.</li>
<li><strong>File metadata</strong> — filenames, sizes, types, and durations of files you interact with, stored to provide browsing and streaming.</li>
<li><strong>Google Drive credentials</strong> — OAuth 2.0 tokens (access and refresh tokens) stored only if you voluntarily connect your Google Drive. Used exclusively to upload files you explicitly request.</li>
</ul>

<h2>How We Use Google API Data</h2>
<p>Aruvi uses the Google Drive API with the <code>drive.file</code> scope to upload files to your personal Google Drive. This scope only allows us to access files and folders that you explicitly create or upload through the service. We do not access, read, or modify any other files in your Google Drive. You can revoke access at any time via <a href="https://myaccount.google.com/permissions">Google Account Permissions</a>.</p>

<h2>What We Do NOT Collect</h2>
<ul>
<li>We do <strong>not</strong> collect your name, email address, IP address, location, device information, or browsing history.</li>
<li>We do <strong>not</strong> use cookies, tracking pixels, analytics services, or advertising.</li>
<li>We do <strong>not</strong> read, store, or transmit the content of your files. All media streams directly from Telegram to your device.</li>
</ul>

<h2>Data Storage & Retention</h2>
<ul>
<li>Your Telegram ID and file metadata are stored in a database. You can request deletion at any time.</li>
<li>Google Drive tokens are retained until you disconnect your account or revoke access.</li>
<li>Inactive accounts may be purged after 6 months of inactivity.</li>
<li>Data is stored on our hosting provider's infrastructure. We implement encryption for data at rest and in transit.</li>
</ul>

<h2>Data Sharing</h2>
<p>We do <strong>not</strong> sell, rent, or share your personal information with third parties for their marketing purposes. Data is shared only with the services you explicitly use:</p>
<ul>
<li><strong>Telegram</strong> — files are stored on Telegram's servers. <a href="https://telegram.org/privacy">Telegram Privacy Policy</a>.</li>
<li><strong>Google Drive</strong> — only if you opt in. <a href="https://policies.google.com/privacy">Google Privacy Policy</a>.</li>
<li><strong>Cloudflare</strong> — DNS and CDN. <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare Privacy Policy</a>.</li>
</ul>

<h2>Your Rights</h2>
<ul>
<li><strong>Access</strong> — request a copy of the data we hold about you.</li>
<li><strong>Deletion</strong> — request deletion of your account and associated data.</li>
<li><strong>Revoke</strong> — revoke Google Drive access anytime via Google Account settings.</li>
<li><strong>Withdraw</strong> — stop using the service at any time.</li>
</ul>
<p>To exercise any of these rights, contact us at the email below.</p>

<h2>Security</h2>
<p>We implement appropriate technical and organizational measures to protect your data, including TLS encryption for all data in transit and encryption of stored OAuth tokens. We follow security best practices and regularly review our code for vulnerabilities.</p>

<h2>Changes to This Policy</h2>
<p>We may update this Privacy Policy from time to time. Material changes will be communicated to users. Continued use after changes constitutes acceptance of the updated policy.</p>

<h2>Contact</h2>
<p>For privacy inquiries, data access, or deletion requests:</p>
<address>
Email: <a href="mailto:priyamolmpraveen2@gmail.com">priyamolmpraveen2@gmail.com</a><br>
Response time: within 7 days
</address>
"""


TERMS_CONTENT = """\
<h1>Terms of Service</h1>
<p class="sub">Last updated: July 27, 2026 · By using Aruvi you agree to these terms.</p>

<h2>Service Description</h2>
<p>Aruvi is a personal media streaming service that allows authorized users to browse, stream, and download files from Telegram, and optionally upload files to their personal Google Drive.</p>

<h2>Eligibility</h2>
<p>You must be an authorized user to access this service. Access is granted via Telegram authentication. The service is intended for individual, non-commercial personal use only.</p>

<h2>User Responsibilities</h2>
<ul>
<li>Comply with all applicable laws and Telegram's Terms of Service.</li>
<li>Do not upload, share, or distribute illegal, infringing, or unauthorized content.</li>
<li>Do not abuse, bypass rate limits, or overload the service.</li>
<li>Keep your Telegram account credentials secure. You are responsible for all activity under your account.</li>
<li>Do not use the service for commercial purposes without explicit written permission.</li>
<li>Do not scrape, crawl, or programmatically access the service.</li>
</ul>

<h2>Acceptable Use</h2>
<ul>
<li>The service is provided for personal media streaming and backup.</li>
<li>Automated access, bots, or scripts are prohibited unless explicitly authorized.</li>
<li>Do not use the service to host, distribute, or share malware, phishing content, or harmful material.</li>
</ul>

<h2>Third-Party Services</h2>
<p>Aruvi relies on third-party services, each with its own terms:</p>
<ul>
<li><strong>Telegram</strong> — file storage and messaging. <a href="https://telegram.org/tos">Telegram Terms of Service</a>.</li>
<li><strong>Google Drive</strong> — optional cloud storage. <a href="https://policies.google.com/terms">Google Terms of Service</a>.</li>
<li><strong>Cloudflare</strong> — CDN and DNS. <a href="https://www.cloudflare.com/website-terms/">Cloudflare Terms</a>.</li>
</ul>

<h2>Google API Disclosure</h2>
<p>Aruvi's use of Google APIs complies with the <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>. We only request the minimum scope necessary (<code>drive.file</code>) and use it solely to upload files you explicitly request to your Google Drive.</p>

<h2>Limitation of Liability</h2>
<p>The service is provided "as is" without warranties of any kind, express or implied. To the maximum extent permitted by law, we are not liable for any damages, data loss, or service interruptions arising from the use of this service.</p>

<h2>Termination</h2>
<p>We reserve the right to suspend or terminate access to the service at any time, with or without cause, including for violations of these terms.</p>

<h2>Changes</h2>
<p>We may update these terms at any time. Continued use after changes constitutes acceptance. We will notify users of material changes via the bot.</p>

<h2>Governing Law</h2>
<p>These terms are governed by the laws of India. Any disputes shall be resolved through good-faith negotiations.</p>

<h2>Contact</h2>
<address>
Email: <a href="mailto:priyamolmpraveen2@gmail.com">priyamolmpraveen2@gmail.com</a>
</address>
"""


@router.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return page("Privacy Policy", PRIVACY_CONTENT, "/privacy")


@router.get("/terms", response_class=HTMLResponse)
async def terms():
    return page("Terms of Service", TERMS_CONTENT, "/terms")
