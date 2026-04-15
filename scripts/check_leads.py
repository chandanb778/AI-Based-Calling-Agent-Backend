import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.supabase_client import get_supabase
sb = get_supabase()
r = sb.table("leads").select("name,phone,budget,location,property_type,lead_score,created_at").execute()
leads = r.data or []
print(f"Total leads in Supabase: {len(leads)}\n")
for row in leads:
    print(f"  {row['lead_score']:5} | {row['name']:15} | {row['phone']:15} | {row['budget']:15} | {row['location']:15} | {row['property_type']}")
