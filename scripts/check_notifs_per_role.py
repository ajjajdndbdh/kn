import os, requests
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
BASE = os.environ.get("REACT_APP_BACKEND_URL","").rstrip("/")

ROLES = {
  "admin":"admin@kainnusantara.id","manager":"manager@kainnusantara.id",
  "finance":"finance@kainnusantara.id","sales":"sales@kainnusantara.id",
  "warehouse":"warehouse@kainnusantara.id","salesadmin":"salesadmin@kainnusantara.id",
}

def login(email):
    r = requests.post(f"{BASE}/api/auth/login", json={"email":email,"password":"demo12345"}, timeout=30)
    return r.json()["token"]

tok = login("admin@kainnusantara.id")
h_adm = {"Authorization":f"Bearer {tok}","X-Entity-Id":"ent_ksc"}
r = requests.post(f"{BASE}/api/notifications/generate", headers=h_adm, timeout=60)
print("admin generate:", r.status_code, r.text[:120])
tok = login("manager@kainnusantara.id")
r = requests.post(f"{BASE}/api/notifications/generate", headers={"Authorization":f"Bearer {tok}","X-Entity-Id":"ent_ksc"}, timeout=60)
print("manager generate:", r.status_code, r.text[:120])

for role,email in ROLES.items():
    tok = login(email)
    h = {"Authorization":f"Bearer {tok}","X-Entity-Id":"ent_ksc"}
    r = requests.get(f"{BASE}/api/notifications?limit=200", headers=h, timeout=30)
    if r.status_code != 200:
        print(f"{role}: HTTP {r.status_code} {r.text[:100]}")
        continue
    data = r.json()
    items = data if isinstance(data, list) else (data.get("notifications") or data.get("items") or [])
    counts = {}; addr = {"me":0,"role":0,"all":0}
    for it in items:
        t = it.get("type","?"); counts[t] = counts.get(t,0)+1
        if it.get("recipient_user"): addr["me"] += 1
        elif it.get("recipient_role") and it.get("recipient_role")!="all": addr["role"] += 1
        else: addr["all"] += 1
    print(f"\n{role}: total={len(items)} addr={addr}")
    for t,c in sorted(counts.items()):
        print(f"    {t}: {c}")
