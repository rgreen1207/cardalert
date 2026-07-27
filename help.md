def run_tracking_engine():
    # 1. RUN ONCE AT STARTUP
    print("[*] System initializing. Executing first-time cookie sync...")
    initial_sync = sync_target_session(force=True)
    if not initial_sync:
        print("[!] Warning: Initial sync failed. Tracker will attempt fallback values.")

    # Target test TCIN (Prismatic Evolutions Super Premium Collection or baseline)
    target_tcin = "1012055696" 
    poll_interval = 30  # check every 30 seconds

    print("[+] Startup complete. Lightweight tracking loop engaged.")
    while True:
        print(f"\n[*] Checking Target stock state for item: {target_tcin}...")
        result = check_target(tcin=target_tcin)
        
        print(f"[-] Status returned: {result['raw_status']}")
        
        # 2. RUN ONLY WHEN NON-200 / BLOCKED STATUS OCCURS
        if result["raw_status"] == "SESSION_EXPIRED_NEEDS_SYNC":
            print("[!] Token expiration or 403 block detected. Triggering dynamic browser resync...")
            
            # This triggers Chromium again, matches the new keys, then securely destroys itself out of memory
            synced = sync_target_session()
            if synced:
                print("[+] Resync completed. Retrying poll instantly...")
                result = check_target(tcin=target_tcin)
                print(f"[-] Retry Status: {result['raw_status']}")
            else:
                print("[-] Resync hit a rate limit or cooldown hurdle. Waiting for next cycle.")

        if result["in_stock"]:
            print(f"[!!!] ALERT: ITEM IN STOCK at Target! Price: ${result['price']}")
            # Implement notification alert mechanics here (e.g., Discord or SMS Webhook)

        # Sleep to avoid rate limits on the lightweight curl execution layer
        time.sleep(poll_interval)

if __name__ == "__main__":
    try:
        run_tracking_engine()
    except KeyboardInterrupt:
        print("\n[-] Monitoring safely terminated by user.")