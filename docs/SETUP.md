# Setup guide

This walks you through installing Craftlehem Panel from scratch, even if you've never used Linux much. It takes about 15 minutes.

**You'll need:**
- A Linux machine that runs (or will run) your Minecraft server: a VPS, a dedicated server, or an old PC at home. Ubuntu 24.04 or Debian 12 is easiest.
- A way to type commands on it. That's usually SSH from your own computer: on Windows, open **PowerShell** and type `ssh yourname@server-ip`.
- Your Minecraft server files in a folder on that machine. If they're on your PC, copy the whole folder over with [WinSCP](https://winscp.net) (Windows) or `scp`.

## 1. Install

Log in to the machine and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/coldskiess/craftlehem-panel/main/get.sh | sudo bash
```

It asks a few questions. Press **Enter** to accept the suggestion in [brackets].

| Question | What to type |
|---|---|
| Full path of the server folder | The folder with `server.properties` or `run.sh`, for example `/home/you/minecraft`. Use the full path starting with `/`. |
| Linux user | Press Enter. This is the account that owns the server files. |
| Start command | For modpacks (NeoForge/Forge) keep `bash run.sh nogui`. Don't use a `startserver.sh` that restarts itself in a loop. |
| Server name / address | Whatever you like. The address is what players type to join (optional). |
| Web port | Press Enter for 8080. If something else already uses it, a free port is suggested. |
| Turn on RCON? | **Y**. The panel needs it for TPS and the player list. |
| Admin username and password | Your login for the panel. |

At the end it prints the address to open, for example `http://192.168.1.50:8080`.

## 2. First steps in the panel

1. **If your server is already running the old way** (a terminal window or `screen`), stop it there by typing `stop`. Then press **Start** in the panel, so the panel manages it from now on.
2. **Settings → Memory:** set how much RAM the server gets. Big modpacks want 8–12 GB. Leave 2–3 GB free for Linux.
3. **Schedule:** a nightly restart at 5am and a backup every 6 hours are already set up. Change them as you like.
4. **Settings → Users:** add logins for your staff with the right role (viewer, moderator or admin).

## 3. Reach it from anywhere (Cloudflare Tunnel)

On your home network the panel works straight away. To use it from your phone on mobile data, or to let staff in, **don't** port-forward 8080. That would send your password over the internet unencrypted. A free Cloudflare Tunnel gives you a secure `https://` address without opening any ports on your router.

You'll need a domain name (about US$10 a year) added to a free Cloudflare account.

1. In the Cloudflare dashboard go to **Networking → Tunnels → Create a tunnel**, choose **Cloudflared**, and name it (for example `panel`).
2. On the install step, pick **Debian** and run the commands it shows on your server. The last one looks like `sudo cloudflared service install <long token>`. The tunnel then shows as **Healthy**.
3. Add a route (**Routes → Add route → Published application**):
   - **Subdomain:** `panel`
   - **Domain:** yours
   - **Service URL:** `http://localhost:8080` (use your panel's port)
4. Tell the panel it's behind HTTPS. Edit the config:
   ```bash
   sudo nano /opt/craftlehem-panel/config.yml
   ```
   Under `panel:`, add the line `  secure_cookies: true` (keep the two spaces at the start). Save with Ctrl+O, Enter, then Ctrl+X, and restart the panel:
   ```bash
   sudo systemctl restart craftlehem-panel
   ```
5. Open `https://panel.yourdomain.com`. Your Minecraft server keeps running throughout.

**Strongly recommended:** add an email lock in front of the panel. In Cloudflare **Zero Trust → Access → Applications**, add `panel.yourdomain.com` with an *Allow* rule for your email address (and your staff's). People who aren't on the list never even see the login page. It's free for small teams.

**Already running something else in Docker with its own Cloudflare tunnel?** You can add the panel as another route on that same tunnel. Use the machine's network IP (for example `http://192.168.1.50:8080`) instead of `localhost`, because `localhost` inside a container means the container itself.

## Useful commands

```bash
sudo systemctl status craftlehem-panel     # is the panel running?
sudo systemctl restart craftlehem-panel    # restart the panel (Minecraft keeps running)
sudo journalctl -u craftlehem-panel -f     # the panel's own log

sudo -u YOURUSER tmux attach -t minecraft  # the real server console - leave with Ctrl+B then D (not Ctrl+C!)

cd /opt/craftlehem-panel
sudo -u YOURUSER venv/bin/python run.py add-user NAME moderator   # add a login from the terminal
sudo -u YOURUSER venv/bin/python run.py reset-password NAME       # forgot a password

sudo bash /opt/craftlehem-panel/update.sh      # update to the latest version
sudo bash /opt/craftlehem-panel/uninstall.sh   # remove the panel (your server is never touched)
```

## Troubleshooting

- **The server won't start, or crashes straight away:** open **Logs → panel/console.log**. It shows everything Java printed, including errors from before Minecraft's own log starts (wrong Java version, not enough memory).
- **The TPS gauge says "Measuring…" forever:** RCON isn't reachable. Check **Settings → Server → Network**: `enable-rcon` on, with a port and password. Then restart the server.
- **"Server didn't stop within 180s":** the panel had to force it. Big modpacks can take a while to save. Raise the wait time in **Settings → Panel**.
- **"The page won't load":**
  - Check the panel is running: `sudo systemctl status craftlehem-panel`.
  - Check your firewall allows the port: `sudo ufw allow 8080/tcp`.
  - Check your VPS provider's own firewall in their dashboard.
- **Backups are slow:** in **Settings → Panel**, set compression to `zstd`. It's several times faster.
- **Players show with rank tags** like `[VIP] Name`: the panel already strips these. If a name still looks wrong, [open an issue](https://github.com/coldskiess/craftlehem-panel/issues) with an example line from the console.

## Where things live

| What | Where |
|---|---|
| Panel settings and logins | `/opt/craftlehem-panel/config.yml` |
| Player stats, schedules, console capture, recycle bin | `/opt/craftlehem-panel/data/` |
| Backups | Next to your server folder in `backups/` (change it in Settings → Panel) |
| Craftlehem Pro add-on (if installed) | `/opt/craftlehem-panel/pro/` |
