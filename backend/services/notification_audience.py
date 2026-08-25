"""notification_audience — SATU penyelesai "siapa yang harus diberi tahu".

FASE N. Sebelum berkas ini, alamat notifikasi ditulis sebagai **nama peran** di titik
kejadian (`recipient_role="manager"`) atau — lebih sering — tidak ditulis sama sekali
(`recipient_role="all"`). Terukur 2026-08-24 pada data demo bersih: **11 dari 35**
notifikasi ber-`recipient_role="all"`, yaitu `low_stock` **9**, `order_approval` **1**,
`internal_request_decided` **1**. Artinya Finance & Sales membuka kotak notifikasinya dan
menemukan sembilan pesan stok kain yang bukan urusan mereka, sementara pesan yang
BENAR-BENAR miliknya tenggelam di antaranya. Kotak notifikasi yang isinya bukan urusan
kita adalah kotak yang berhenti dibaca — dan sesudah itu peringatan pertama yang
sungguh penting pun ikut tak terbaca.

## Kenapa ALAMAT tidak boleh berupa nama peran yang diketik di titik kejadian

1. **Nama peran bukan wewenang.** "Siapa yang harus tahu stok menipis?" jawabannya
   *"yang boleh menerbitkan pesanan pembelian"* — dan yang menentukan itu **matriks
   izin** (`permission_settings`, bisa diubah pemilik dari layar), bukan konstanta di
   kode. Begitu pemilik memberi `purchase_order.create` kepada peran baru, alamat
   notifikasinya HARUS ikut, tanpa ada yang mengedit kode. Ini kelas cacat yang sama
   dengan `INV-ROLE-01` ("peran hanya dari registry & wewenang hanya dari IZIN"),
   sekarang untuk jalur notifikasi.
2. **`recipient_role` + `recipient_user` sekaligus = pagarnya BOCOR.** Penyaring
   pembaca (`routers/notifications.py:_scope_query`) memakai **OR**:
   `{recipient_role ∈ {peran_saya, "all"}} OR {recipient_user == saya}`. Jadi
   `recipient_role="sales", recipient_user=<sales pemegang akun>` TIDAK berarti
   "hanya sales itu" — ia berarti **SELURUH sales**. Terukur di `alert_ops_service`
   (`ar_due_soon`) dan `internal_request_service` (`internal_request_decided`):
   keduanya menulis kedua field, dan keduanya menyangka sedang menyempitkan alamat
   padahal sedang menyiarkan. Satu-satunya alamat yang benar-benar sempit adalah
   **`recipient_user` SENDIRI** (tanpa `recipient_role`).
3. **Karena itu alamat berbasis izin harus DISEBAR PER ORANG**, bukan disimpan sebagai
   query izin di dokumen: pembaca tidak boleh diminta menghitung ulang matriks izin
   setiap kali membuka kotaknya (dan kalau izinnya dicabut besok, pesan lama tetap
   milik orang yang menerimanya — jejak tidak boleh berubah retroaktif).

## Aturan yang dipegang berkas ini
* **Entitas ikut menyaring.** Penerima hanya orang yang memang bertugas di badan usaha
  dokumen itu (`home_entity_id` atau `allowed_entity_ids`). `entity_id` kosong =
  peristiwa sistem → semua yang berwenang.
* **Dedupe per ORANG.** Satu orang yang lolos lewat DUA jalan (punya izinnya *dan*
  anggota divisinya) tetap menerima **satu** notifikasi.
* **Urutan stabil** (diurutkan per id) supaya POC & gate bisa membandingkan hasil.
* **Nonaktif tidak diberi tahu** (`status != "active"` dilewati).
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from db import db

# Divisi (departemen HR) dipetakan lewat `hr_employees.department_id` → `hr_org_units`.
# Pencocokan sengaja LONGGAR (id / kode / nama, tanpa peduli huruf besar-kecil) karena
# yang mengisi setelan ini adalah pemilik lewat layar Pengaturan, bukan programmer:
# "md", "DEPT-002", "Penjualan" dan "penjualan" harus sama-sama mengena. Kalau tidak
# ada yang cocok, hasilnya HIMPUNAN KOSONG — bukan galat dan bukan "kirim ke semua".
_ORG_COLL = "hr_org_units"
_EMP_COLL = "hr_employees"


async def roles_with_permission(module: str, action: str) -> List[str]:
    """Peran yang memegang `module.action` menurut MATRIKS IZIN yang berlaku.

    Sumbernya `dependencies.permission_matrix()` — matriks di basis data bila pemilik
    sudah mengubahnya, jatuh ke `permissions_config.DEFAULT_PERMISSIONS` bila belum.
    Satu pembaca, supaya alamat notifikasi tidak pernah berbeda dari yang ditegakkan
    endpoint-nya.
    """
    from dependencies import permission_matrix

    matrix = await permission_matrix()
    out: List[str] = []
    for role, perms in (matrix or {}).items():
        allowed = (perms or {}).get(module) or []
        if action in allowed or "*" in allowed:
            out.append(str(role))
    return sorted(out)


def _sees_entity(user: Dict[str, Any], entity_id: Optional[str]) -> bool:
    """Apakah `user` bertugas di badan usaha `entity_id`.

    Mengikuti aturan yang sama dengan `entity_scope`: daftar penugasan adalah
    `allowed_entity_ids`, dan bila kosong maka penugasannya = badan usaha rumahnya.
    """
    if not entity_id:
        return True                      # peristiwa sistem — tidak terikat satu PT
    home = str(user.get("home_entity_id") or "")
    assigned = [str(x) for x in (user.get("allowed_entity_ids") or []) if x] or (
        [home] if home else [])
    return entity_id in assigned


async def _users_by_roles(roles: Sequence[str],
                          entity_id: Optional[str]) -> List[Dict[str, Any]]:
    if not roles:
        return []
    rows = await db.users.find(
        {"role": {"$in": list(roles)}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
         "status": 1, "home_entity_id": 1, "allowed_entity_ids": 1},
    ).to_list(500)
    return [u for u in rows
            if str(u.get("status") or "active") == "active"
            and _sees_entity(u, entity_id)]


async def _users_in_division(division: str,
                             entity_id: Optional[str]) -> List[Dict[str, Any]]:
    """Karyawan pada satu departemen HR yang PUNYA akun pengguna.

    Karyawan tanpa `user_id` sengaja dilewati: notifikasi in-app hanya bisa dibaca
    lewat akun. (Terukur pada data demo: 13 dari 15 karyawan punya akun.)
    """
    want = str(division or "").strip().lower()
    if not want:
        return []
    unit_q: Dict[str, Any] = {}
    if entity_id:
        unit_q["entity_id"] = entity_id
    units = await db[_ORG_COLL].find(
        unit_q, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(500)
    unit_ids = [u["id"] for u in units
                if want in {str(u.get("id") or "").lower(),
                            str(u.get("code") or "").lower(),
                            str(u.get("name") or "").lower()}]
    if not unit_ids:
        return []
    emp_q: Dict[str, Any] = {"department_id": {"$in": unit_ids},
                             "user_id": {"$nin": ["", None]}}
    if entity_id:
        emp_q["entity_id"] = entity_id
    emps = await db[_EMP_COLL].find(emp_q, {"_id": 0, "user_id": 1}).to_list(500)
    uids = sorted({str(e["user_id"]) for e in emps if e.get("user_id")})
    if not uids:
        return []
    rows = await db.users.find(
        {"id": {"$in": uids}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
         "status": 1, "home_entity_id": 1, "allowed_entity_ids": 1},
    ).to_list(500)
    return [u for u in rows
            if str(u.get("status") or "active") == "active"
            and _sees_entity(u, entity_id)]


async def resolve_recipients(
    *,
    permission: Optional[Tuple[str, str]] = None,
    division: str = "",
    roles: Sequence[str] = (),
    entity_id: Optional[str] = None,
    also_users: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """Kumpulkan penerima dari GABUNGAN sumber, lalu dedupe per orang.

    * `permission=("purchase_order", "create")` → semua pemegang wewenang itu;
    * `division="md"` → semua anggota departemen itu yang punya akun;
    * `roles=("manager",)` → peran tertentu (dipakai bila alamatnya memang jabatan);
    * `also_users=(uid, …)` → orang tertentu (mis. pemohon / petugas yang ditugaskan).

    Return: daftar user (dedupe per `id`, urut stabil). Kosong = TIDAK ADA yang
    diberi tahu — pemanggil harus memutuskan apakah itu wajar; berkas ini sengaja
    TIDAK pernah jatuh kembali ke "kirim ke semua orang", karena justru itu cacat
    yang ingin ditutup FASE N.
    """
    found: Dict[str, Dict[str, Any]] = {}

    role_set: List[str] = [str(r) for r in roles if r]
    if permission:
        role_set = sorted(set(role_set) |
                          set(await roles_with_permission(permission[0], permission[1])))
    for u in await _users_by_roles(role_set, entity_id):
        found[str(u["id"])] = u
    for u in await _users_in_division(division, entity_id):
        found.setdefault(str(u["id"]), u)

    extra = [str(x) for x in also_users if x]
    if extra:
        rows = await db.users.find(
            {"id": {"$in": extra}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
             "status": 1, "home_entity_id": 1, "allowed_entity_ids": 1},
        ).to_list(200)
        for u in rows:
            # Orang yang DISEBUT namanya (pemohon, petugas yang ditugaskan) tetap
            # diberi tahu walau perannya tidak memegang izin peristiwa itu —
            # ia memang pihak dalam dokumen tersebut. Pagar entitas tetap berlaku.
            if str(u.get("status") or "active") == "active" and _sees_entity(u, entity_id):
                found.setdefault(str(u["id"]), u)

    return [found[k] for k in sorted(found)]
