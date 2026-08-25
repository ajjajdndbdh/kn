#!/usr/bin/env python3
"""Pengintai residu `system_settings`: rekam SIAPA yang menambah baris saat gate jalan.

Dipakai sekali untuk memburu residu +4 yang hanya muncul pada gate PENUH (tidak
muncul saat POC dijalankan satu-satu). Menyimpan dokumen baru + waktu ke
/app/.logs/intip_settings.jsonl.
"""
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
OUT = Path("/app/.logs/intip_settings.jsonl")
seen = {d["id"] for d in db.system_settings.find({}, {"id": 1})}
with OUT.open("w") as fh:
    fh.write(json.dumps({"t": time.strftime("%H:%M:%S"), "awal": len(seen)}) + "\n")
    fh.flush()
    while True:
        for d in db.system_settings.find({}):
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            d.pop("_id", None)
            fh.write(json.dumps({"t": time.strftime("%H:%M:%S"),
                                 "baru": {k: str(v)[:120] for k, v in d.items()}}) + "\n")
            fh.flush()
        time.sleep(0.4)
