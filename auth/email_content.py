"""
What a password-reset email says, and how it looks.

SEPARATE FROM TRANSPORT ON PURPOSE. Rendering the message and delivering it are
different concerns with different failure modes: one is a string, the other is a
network call. Keeping them apart means the wording, the escaping and the
absence-of-secrets can be tested without a provider, a key or a socket.

WHAT THE COPY MAY NOT CLAIM. The request arrived at an unauthenticated endpoint
from someone who typed an address. That is all anybody knows. So the email says
"someone asked", never "you asked", and offers ignoring it as a normal outcome
rather than an alarm -- a stranger's typo should not read as a break-in, and a
real attempt should not read as routine.

WHAT IT MAY NOT CONTAIN. No password, no hash, no session token, no token hash,
no user id, no database id, no diagnostics. The reset URL is the single secret
here, and it is the only one that belongs in an inbox.

NO IMAGES, NO REMOTE ANYTHING. No logo file, no web font, no tracking pixel --
so there is nothing for a client to block, nothing to leak that the message was
opened, and nothing that turns into a broken-image box when it is. The mark is
the wordmark set in letterspaced caps with the brand rule beneath it, which is
the part of the identity that survives an email client intact.

A LIGHT PALETTE, THOUGH THE PRODUCT IS DARK. Gmail and Outlook apply their own
dark-mode heuristics to email, and they invert dark-on-dark unpredictably --
often bleaching exactly the low-contrast text this message depends on. The one
thing that must stay legible in every client is the fallback URL, so the email
is light with the brand accent, rather than a faithful reproduction of an
interface nobody is looking at while they read it.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

#: Says what it is and who it is from, in the length a phone shows.
SUBJECT = "Reset your Subterra AI password"

# Brand tokens, converted from the oklch values in the frontend theme, because
# no email client understands oklch.
_INK = "#0a0f13"          # --foreground, inverted for a light ground
_ACCENT = "#34bfcd"       # --primary
_MUTED = "#5b6570"        # --muted-foreground, darkened for light-ground contrast
_RULE = "#e3e7ea"
_PAGE = "#f4f6f7"


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


def password_reset_content(reset_url: str, ttl_minutes: int) -> EmailContent:
    """
    Render both bodies for one reset link.

    Both are produced together and from the same inputs, so the plain-text
    fallback cannot drift into saying something the HTML does not -- the usual
    way a text alternative ends up with a stale expiry or a missing link.
    """
    expiry = _expiry_phrase(ttl_minutes)
    return EmailContent(
        subject=SUBJECT,
        text=_text_body(reset_url, expiry),
        html=_html_body(reset_url, expiry),
    )


def _expiry_phrase(ttl_minutes: int) -> str:
    """`30 minutes`, `1 hour`, `2 hours` -- read from the configured TTL, never
    written into the copy by hand, so shortening the TTL cannot leave the email
    promising the old one."""
    minutes = max(1, int(ttl_minutes))
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hour" if hours == 1 else f"{hours} hours"
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def _text_body(reset_url: str, expiry: str) -> str:
    """
    The plain-text alternative. Not a courtesy: some clients render only this,
    some corporate gateways strip HTML outright, and a screen reader is happier
    with it. The URL is bare so it stays clickable and, more importantly,
    copyable.
    """
    return (
        "SUBTERRA AI\n"
        "\n"
        "Reset your password\n"
        "\n"
        "Someone asked to reset the password for the Subterra AI account with\n"
        "this email address. Open the link below to choose a new one:\n"
        "\n"
        f"{reset_url}\n"
        "\n"
        f"The link works once and expires in {expiry}.\n"
        "\n"
        "If you did not ask for this, you can ignore this message -- your\n"
        "password will not change until the link above is used.\n"
        "\n"
        "This message was sent automatically. Please do not reply.\n"
    )


def _html_body(reset_url: str, expiry: str) -> str:
    """
    Table-based, inline-styled, and deliberately plain.

    Email clients are not browsers: no flexbox, no grid, no external
    stylesheet, and Outlook still lays out with Word. Tables and inline styles
    are not a stylistic choice here, they are the only reliable ones.

    THE URL APPEARS TWICE, as the button target and as visible text. Buttons are
    what people click; the visible copy is what survives a client that strips
    the anchor, a forwarded plain-text quote, or a reader who wants to see where
    a link goes before trusting it -- which is precisely the habit a
    password-reset email should reward rather than defeat.
    """
    href = html.escape(reset_url, quote=True)
    shown = html.escape(reset_url, quote=False)

    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(SUBJECT)}</title>
</head>
<body style="margin:0;padding:0;background:{_PAGE};">
<!-- Preheader: the grey line clients show next to the subject. Hidden in the
     body itself, so it is not repeated on screen. -->
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
Use the link inside to choose a new password. It expires in {expiry}.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{_PAGE};padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:520px;background:#ffffff;border:1px solid {_RULE};
                    border-radius:12px;padding:36px 34px;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
        <tr>
          <td style="padding-bottom:26px;">
            <div style="font-size:12px;font-weight:700;letter-spacing:0.22em;
                        text-transform:uppercase;color:{_INK};">Subterra&nbsp;AI</div>
            <div style="height:2px;width:34px;background:{_ACCENT};margin-top:9px;"></div>
          </td>
        </tr>
        <tr>
          <td style="font-size:21px;font-weight:600;color:{_INK};padding-bottom:14px;">
            Reset your password
          </td>
        </tr>
        <tr>
          <td style="font-size:15px;line-height:1.6;color:{_MUTED};padding-bottom:26px;">
            Someone asked to reset the password for the Subterra AI account with
            this email address. Use the button below to choose a new one.
          </td>
        </tr>
        <tr>
          <td style="padding-bottom:24px;">
            <a href="{href}"
               style="display:inline-block;background:{_INK};color:#ffffff;
                      font-size:15px;font-weight:600;text-decoration:none;
                      padding:13px 26px;border-radius:8px;">Choose a new password</a>
          </td>
        </tr>
        <tr>
          <td style="font-size:14px;line-height:1.6;color:{_MUTED};padding-bottom:22px;">
            The link works once and expires in {expiry}.
          </td>
        </tr>
        <tr>
          <td style="font-size:13px;line-height:1.6;color:{_MUTED};
                     border-top:1px solid {_RULE};padding-top:22px;padding-bottom:18px;">
            If you did not ask for this, you can ignore this message &mdash; your
            password will not change until the link above is used.
          </td>
        </tr>
        <tr>
          <td style="font-size:12px;line-height:1.6;color:{_MUTED};word-break:break-all;">
            If the button does not work, copy this address into your browser:<br>
            <span style="color:{_INK};">{shown}</span>
          </td>
        </tr>
        <tr>
          <td style="font-size:12px;line-height:1.6;color:{_MUTED};padding-top:22px;">
            This message was sent automatically. Please do not reply.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""
