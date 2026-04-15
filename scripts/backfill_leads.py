"""
Backfill leads from existing call transcripts in Supabase.

This script:
1. Fetches all call_logs from Supabase
2. Checks which ones already have a lead (by phone number)
3. Runs Groq lead extraction on the remaining transcripts
4. Inserts the extracted leads into the leads table
"""

import asyncio
import sys
import os
import io

# Fix Windows encoding for emoji output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.supabase_client import get_supabase
from app.services.lead_service import extract_lead_from_transcript
from app.db.leads import insert_lead


async def main():
    supabase = get_supabase()

    # 1. Fetch all call logs
    print("\n[1] Fetching call logs from Supabase...")
    result = supabase.table("call_logs").select("*").order("created_at", desc=True).execute()
    call_logs = result.data or []
    print(f"    Found {len(call_logs)} call logs")

    if not call_logs:
        print("    No call logs to process. Exiting.")
        return

    # 2. Fetch existing leads to avoid duplicates
    print("[2] Fetching existing leads...")
    leads_result = supabase.table("leads").select("phone").execute()
    existing_phones = set(row["phone"] for row in (leads_result.data or []))
    print(f"    Found {len(existing_phones)} existing leads")

    # 3. Process each call log
    new_leads = 0
    skipped = 0
    failed = 0

    for i, log in enumerate(call_logs, 1):
        phone = log.get("caller_number", "")
        transcript = log.get("transcript", "")

        # Skip if already has a lead
        if phone in existing_phones:
            print(f"    [{i}/{len(call_logs)}] SKIP  {phone} -- already has a lead")
            skipped += 1
            continue

        # Skip empty transcripts
        if not transcript or transcript == "(no transcript captured)":
            print(f"    [{i}/{len(call_logs)}] SKIP  {phone} -- no transcript")
            skipped += 1
            continue

        print(f"    [{i}/{len(call_logs)}] PROCESSING {phone}...")
        preview = transcript[:120].replace("\n", " ")
        print(f"        Transcript: {preview}...")

        try:
            lead_data = await extract_lead_from_transcript(
                transcript=transcript,
                phone_number=phone,
                contact_name="",
            )

            if lead_data:
                result = await insert_lead(lead_data)
                if result:
                    existing_phones.add(phone)
                    new_leads += 1
                    print(f"        OK  score={lead_data.get('lead_score')}, "
                          f"budget={lead_data.get('budget')}, "
                          f"location={lead_data.get('location')}")
                else:
                    failed += 1
                    print(f"        FAIL  Could not save to Supabase")
            else:
                failed += 1
                print(f"        FAIL  Could not extract lead data")

        except Exception as e:
            failed += 1
            print(f"        ERROR  {e}")

        # Small delay to respect Groq rate limits
        await asyncio.sleep(1)

    # 4. Summary
    print(f"\n{'='*50}")
    print(f"BACKFILL COMPLETE")
    print(f"  New leads created : {new_leads}")
    print(f"  Skipped           : {skipped}")
    print(f"  Failed            : {failed}")
    print(f"  Total call logs   : {len(call_logs)}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    asyncio.run(main())
