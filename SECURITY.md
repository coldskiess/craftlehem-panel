# Security

The panel can start, stop and change your server, so security reports matter.

**Please don't open a public issue for a security problem.** Report it privately through GitHub's
"Report a vulnerability" button on this repository (Security tab), or message coldskiess on Gumroad.
Include what you found, how to reproduce it and which version you tested. You'll get a reply as
soon as possible, and a fix release before details are made public.

Tips for running the panel safely:
- Don't expose the panel's port directly to the internet. Use HTTPS through a Cloudflare Tunnel
  (see docs/SETUP.md) or a reverse proxy, and set `secure_cookies: true`.
- Give staff the lowest role they need (viewer → moderator → admin).
- Keep RCON's port (25575) closed to the internet. The panel connects to it from the same machine.
- Keep the panel updated: `sudo bash update.sh`.
