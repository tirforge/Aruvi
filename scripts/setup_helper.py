"""
Aruvi Setup Helper — get channel/group IDs + user session strings via GitHub Codespaces or locally.

Run:  python scripts/setup_helper.py
Needs: pip install telethon

GitHub Codespaces: click 'Code → Create codespace on main' → run the command above.
Local: same command, Python 3.11+ required.

🌐 Web helper available: https://aaruvi.space/setup.html — fill API_ID/HASH + channel IDs → generate .env snippet instantly.
"""
# Brand colors (matching aaruvi.space theme: --accent: #6366f1)
BR_PURPLE = "\033[38;2;99;102;241m"   # RGB accent purple
BR_RESET  = "\033[0m"
BR_BOLD   = "\033[1m"
BR_DIM    = "\033[2m"
OK_GREEN  = "\033[32m"
WARN_YELL = "\033[33m"
FAIL_RED  = "\033[31m"

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

def prompt_api():
    print("\nStep 1 — Telegram API credentials")
    print("Get from https://my.telegram.org → API development tools → Create app")
    api_id = input("Enter API_ID (numbers only): ").strip()
    api_hash = input("Enter API_HASH: ").strip()
    return int(api_id), api_hash

def gen_session(api_id, api_hash):
    print("\nStep 2 — Generate user session string")
    print("You will be asked for phone (+91...), login code, and 2FA password if set.")
    client = TelegramClient(StringSession(), api_id, api_hash)
    client.start()
    sess = client.session.save()
    print(f"\n{OK_GREEN}✓{BR_RESET} Your SESSION STRING (copy the whole line, keep it secret):")
    print(sess)
    print("\nPaste it in .env as: GRAB_SESSION_STRINGS=<this_string>")
    return sess, client

def list_ids(client):
    print(f"\n{BR_PURPLE}Step 3 — Your channels/groups and IDs{BR_RESET}")
    print("Fetching dialogs (this may take a few seconds)...\n")
    dialogs = client.get_dialogs()
    # Filter channels/groups
    rows = []
    for d in dialogs:
        ent = d.entity
        # entity types: Channel, Chat, User
        from telethon.tl.types import Channel, Chat
        if isinstance(ent, (Channel, Chat)):
            # channel ID format for .env is -100 + id for channels/supergroups
            cid = ent.id
            # Telethon gives bare ID; for supergroups/channels the -100 prefix is needed
            # We show both forms
            display_id = f"-100{cid}" if getattr(ent, 'megagroup', False) or getattr(ent, 'broadcast', False) else str(cid)
            username = getattr(ent, 'username', None) or "(no username)"
            title = getattr(ent, 'title', 'Chat')
            rows.append((title, username, display_id, cid))
    # Sort by title
    rows.sort(key=lambda x: x[0].lower())
    print(f"{'Title':<30} {'Username':<25} {'ID for .env':<18} {'Bare ID'}")
    print(f"{BR_DIM}{'-'*90}{BR_RESET}")
    for title, username, disp, bare in rows[:50]:
        print(f"{title[:30]:<30} {username[:25]:<25} {disp:<18} {bare}")
    print(f"\n{BR_DIM}Tip: For TELEGRAM_STORAGE_CHANNEL_ID use the 'ID for .env' (-100...).{BR_RESET}")
    print(f"For GRAB_GROUP_USERNAMES use the 'Username' (without @). If no username, you must add one in Telegram Group Info or use invite link (join first).{BR_RESET}")

def check_bot_access(api_id, api_hash, channel_id, helper_bots):
    """Check if each bot token can access the storage channel (bot must be admin).
    Uses Telethon in bot mode: TelegramClient(...).start(bot_token=token)
    """
    results = {}
    for bot_token in helper_bots:
        if not bot_token or ":" not in bot_token:
            results[bot_token] = {'access': False, 'error': 'Invalid bot token (missing :)'} 
            continue
        try:
            c = TelegramClient(StringSession(), api_id, api_hash)
            c.start(bot_token=bot_token)
            if c.is_connected:
                try:
                    # channel_id comes as -100... string; Telethon accepts int
                    cid = int(str(channel_id).strip())
                    msg = c.get_messages(cid, limit=1)
                    # msg is list or single; treat empty as no access
                    has_access = bool(msg)
                    results[bot_token] = {'access': has_access, 'error': None if has_access else 'No messages / not admin'}
                except Exception as e:
                    results[bot_token] = {'access': False, 'error': str(e)}
            else:
                results[bot_token] = {'access': False, 'error': 'Not connected'}
            c.disconnect()
        except Exception as e:
            results[bot_token] = {'access': False, 'error': f'Client error: {e}'}
    return results

def _p(text):
    """Print with brand purple accent."""
    print(f"{BR_PURPLE}{text}{BR_RESET}")

def _p_bold(text):
    """Print with brand purple accent + bold."""
    print(f"{BR_PURPLE}{BR_BOLD}{text}{BR_RESET}")

def _p_warn(text):
    print(f"{WARN_YELL}{text}{BR_RESET}")

def _p_ok(text):
    print(f"{OK_GREEN}{text}{BR_RESET}")

def _sep():
    print(f"{BR_DIM}-" * 60 + BR_RESET)

def main():
    _p_bold("Aruvi Setup Helper")
    _p("get channel/group IDs + user session strings")
    _p("Web helper: https://aaruvi.space/setup.html  |  Codespaces: python scripts/setup_helper.py")
    _p("")

    api_id, api_hash = prompt_api()

    _p("")
    _p_bold("What to do?")
    _p("   1) Generate session string only")
    _p("   2) List my channels/groups IDs (needs session)")
    _p("   3) Both — generate session then list IDs (recommended)")
    _p("   4) Verify bot access to storage channel")
    _p("")
    choice = input("Choose 1/2/3/4 [3]: ").strip() or "3"

    client = None
    sess = None
    if choice in ("1", "3"):
        sess, client = gen_session(api_id, api_hash)
    elif choice == "2":
        # Ask for existing session string
        sess = input("Paste your existing StringSession: ").strip()
        from telethon.sync import TelegramClient as TC2
        from telethon.sessions import StringSession as SS2
        client = TC2(SS2(sess), api_id, api_hash)
        client.start()

    if choice in ("2", "3"):
        if client is None:
            # Should not happen, but fallback
            sess, client = gen_session(api_id, api_hash)
        try:
            list_ids(client)
        finally:
            client.disconnect()

    if choice == "4":
        # Verify bot access to storage channel
        channel_id = input("Enter storage channel ID (-100...): ").strip()
        if not channel_id.startswith("-100"):
            _p_warn("⚠ Channel ID should have -100 prefix")
        helper_input = input("Enter helper bot tokens (comma-separated, from .env TELEGRAM_HELPER_BOT_TOKENS): ").strip()
        helper_bots = [t.strip() for t in helper_input.split(",") if t.strip()]
        if not helper_bots:
            _p_warn("No helper tokens entered — using .env defaults...")
            import os
            helper_bots = os.environ.get("TELEGRAM_HELPER_BOT_TOKENS", "").split(",")

        _p(f"\nVerifying {len(helper_bots)} helper bot(s) access to channel {channel_id}...")
        results = check_bot_access(api_id, api_hash, channel_id, helper_bots)

        _p(f"{'Bot Token':<25} {'Access':<8} {'Issue'}")
        _sep()
        all_ok = True
        for token, r in results.items():
            status = "✓" if r['access'] else "✗"
            issue = r['error'][:30] if r['error'] else "—"
            _p_status = OK_GREEN if r['access'] else FAIL_RED
            _p(f"{token[:24]:<25} {_p_status}{status:<8}{BR_RESET} {issue}")
            if not r['access']:
                all_ok = False

        if all_ok:
            _p_ok("\n✓ All helper bots have access to the storage channel!")
        else:
            _p_warn(f"\n⚠ {len([r for r in results.values() if not r['access']])} bot(s) cannot access the channel.")
            _p("   • Add them as admins with 'Post messages' permission")
            _p("   • Or check they are not restricted by FloodWait etc.")

    _p("")
    _p_bold("Done. Next steps:")
    _p("- Put IDs in .env: TELEGRAM_STORAGE_CHANNEL_ID=-100... and GRAB_GROUP_USERNAMES=group1,group2")
    _p("- Put session strings in .env: GRAB_SESSION_STRINGS=<string1>,<string2>")
    _p("- See docs/grabber.md for full guide  |  Or use web: https://aaruvi.space/setup.html")


if __name__ == "__main__":
    main()