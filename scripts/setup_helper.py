"""
Aruvi Setup Helper — get channel/group IDs + user session strings via GitHub Codespaces or locally.

Run:  python scripts/setup_helper.py
Needs: pip install telethon

GitHub Codespaces: click 'Code → Create codespace on main' → run the command above.
Local: same command, Python 3.11+ required.
"""
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
    print("\n✓ Your SESSION STRING (copy the whole line, keep it secret):")
    print(sess)
    print("\nPaste it in .env as: GRAB_SESSION_STRINGS=<this_string>")
    return sess, client

def list_ids(client):
    print("\nStep 3 — Your channels/groups and IDs")
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
    print("-" * 90)
    for title, username, disp, bare in rows[:50]:
        print(f"{title[:30]:<30} {username[:25]:<25} {disp:<18} {bare}")
    print("\nTip: For TELEGRAM_STORAGE_CHANNEL_ID use the 'ID for .env' (-100...).")
    print("For GRAB_GROUP_USERNAMES use the 'Username' (without @). If no username, you must add one in Telegram Group Info or use invite link (join first).")

def main():
    print("=== Aruvi Setup Helper ===")
    print("This helps you get: 1) user session strings (needs phone) 2) Channel/Group IDs")
    print("It runs via GitHub Codespaces or locally — no data leaves your machine.")
    api_id, api_hash = prompt_api()
    print("\nWhat to do?")
    print("1) Generate session string only")
    print("2) List my channels/groups IDs (needs session)")
    print("3) Both — generate session then list IDs (recommended for first-time setup)")
    choice = input("Choose 1/2/3 [3]: ").strip() or "3"

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

    print("\nDone. Next steps:")
    print("- Put IDs in .env: TELEGRAM_STORAGE_CHANNEL_ID=-100... and GRAB_GROUP_USERNAMES=group1,group2")
    print("- Put session strings in .env: GRAB_SESSION_STRINGS=<string1>,<string2>")
    print("- See docs/grabber.md for full guide.")

if __name__ == "__main__":
    main()
