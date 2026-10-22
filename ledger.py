# ledger.py — Satu pintu untuk semua pergerakan stok & kas Risena
# ─────────────────────────────────────────────────────────────────────────
# Semua fitur (order, restok bahan, produksi, konsinyasi, koreksi manual)
# mengubah stok dan arus kas LEWAT fungsi di file ini, supaya:
#   • setiap perubahan stok tercatat di tabel stock_movements (kartu stok)
#   • setiap kas otomatis punya referensi ke asalnya (ref_type + ref_id)
#   • pembatalan (hapus order / konsinyasi / produksi) bisa mengembalikan
#     stok dan kas secara persis lewat undo_ref()
# ─────────────────────────────────────────────────────────────────────────
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from database import fmt_date_id

_TABLES = {"product": "products", "material": "materials"}


def now_iso() -> str:
    """Waktu sekarang (UTC) dengan format yang sama dengan toISOString() di browser."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def today_str() -> str:
    return fmt_date_id(datetime.now())


# ─────────────────────────────────────────────────────
# STOK
# ─────────────────────────────────────────────────────
def log_movement(conn: sqlite3.Connection, item_type: str, item_id: int, nama: str,
                 qty: float, stok_sesudah: float, ref_type: str, ref_id: str,
                 catatan: str = "", unit_cost: float = 0.0,
                 tanggal: Optional[str] = None) -> None:
    """Catat 1 baris mutasi stok (tanpa mengubah stok itu sendiri)."""
    if qty == 0:
        return
    conn.execute(
        "INSERT INTO stock_movements "
        "(tanggal,item_type,item_id,nama,qty,stok_sesudah,unit_cost,ref_type,ref_id,catatan) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tanggal or now_iso(), item_type, item_id, nama, qty, stok_sesudah,
         unit_cost, ref_type, str(ref_id), catatan),
    )


def apply_stock(conn: sqlite3.Connection, item_type: str, item_id: int, delta: float,
                ref_type: str, ref_id: str, catatan: str = "", unit_cost: float = 0.0,
                allow_negative: bool = False) -> Optional[dict]:
    """
    Ubah stok produk/bahan sebesar `delta` (+ masuk, − keluar) dan catat mutasinya.
    Stok tidak pernah di bawah 0 (kecuali allow_negative). Yang dicatat adalah
    perubahan yang BENAR-BENAR terjadi, supaya pembatalan nanti akurat.
    """
    table = _TABLES[item_type]
    row = conn.execute(f"SELECT nama, stok FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    old = float(row["stok"])
    new = old + delta
    if not allow_negative and new < 0:
        new = 0.0
    new = int(round(new)) if item_type == "product" else round(new, 6)
    applied = new - old
    conn.execute(f"UPDATE {table} SET stok=? WHERE id=?", (new, item_id))
    log_movement(conn, item_type, item_id, row["nama"], applied, new,
                 ref_type, ref_id, catatan, unit_cost)
    shortfall = max(0.0, applied - delta) if delta < 0 else 0.0
    return {"old": old, "new": new, "applied": applied, "shortfall": shortfall,
            "nama": row["nama"]}


def undo_ref(conn: sqlite3.Connection, ref_type: str, ref_id: str) -> int:
    """
    Batalkan SEMUA mutasi stok milik satu referensi (mis. order ORD-12):
    stok dikembalikan sebesar total mutasinya, lalu barisnya dihapus.
    Data lama yang belum punya mutasi dilewati (aman, tidak mengubah apa pun).
    """
    rows = conn.execute(
        "SELECT item_type, item_id, SUM(qty) AS total FROM stock_movements "
        "WHERE ref_type=? AND ref_id=? GROUP BY item_type, item_id",
        (ref_type, str(ref_id)),
    ).fetchall()
    for r in rows:
        table = _TABLES[r["item_type"]]
        cur = conn.execute(f"SELECT stok FROM {table} WHERE id=?", (r["item_id"],)).fetchone()
        if not cur:
            continue
        new = max(0.0, float(cur["stok"]) - float(r["total"]))
        new = int(round(new)) if r["item_type"] == "product" else round(new, 6)
        conn.execute(f"UPDATE {table} SET stok=? WHERE id=?", (new, r["item_id"]))
    conn.execute("DELETE FROM stock_movements WHERE ref_type=? AND ref_id=?",
                 (ref_type, str(ref_id)))
    return len(rows)


def has_movements(conn: sqlite3.Connection, ref_type: str, ref_id: str) -> bool:
    r = conn.execute("SELECT 1 FROM stock_movements WHERE ref_type=? AND ref_id=? LIMIT 1",
                     (ref_type, str(ref_id))).fetchone()
    return r is not None


# ─────────────────────────────────────────────────────
# KAS
# ─────────────────────────────────────────────────────
def cashflow_add(conn: sqlite3.Connection, cf_type: str, amount: float, desc: str,
                 category: str, ref_type: str = "", ref_id: str = "",
                 date_iso: Optional[str] = None, date_str: Optional[str] = None) -> str:
    cf_id = f"CF-{int(time.time() * 1000)}"
    # hindari tabrakan ID bila dua kas dibuat di milidetik yang sama
    n = 0
    while conn.execute("SELECT 1 FROM cashflows WHERE id=?", (cf_id,)).fetchone():
        n += 1
        cf_id = f"CF-{int(time.time() * 1000)}-{n}"
    conn.execute(
        "INSERT INTO cashflows (id,type,date,date_str,desc_text,category,amount,ref_type,ref_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (cf_id, cf_type, date_iso or now_iso(), date_str or today_str(),
         desc, category, amount, ref_type, str(ref_id)),
    )
    return cf_id


def cashflow_remove(conn: sqlite3.Connection, ref_type: str, ref_id: str) -> int:
    cur = conn.execute("DELETE FROM cashflows WHERE ref_type=? AND ref_id=?",
                       (ref_type, str(ref_id)))
    return cur.rowcount


def cashflow_upsert(conn: sqlite3.Connection, cf_type: str, amount: float, desc: str,
                    category: str, ref_type: str, ref_id: str) -> str:
    row = conn.execute("SELECT id FROM cashflows WHERE ref_type=? AND ref_id=?",
                       (ref_type, str(ref_id))).fetchone()
    if row:
        conn.execute("UPDATE cashflows SET amount=?, desc_text=? WHERE id=?",
                     (amount, desc, row["id"]))
        return row["id"]
    return cashflow_add(conn, cf_type, amount, desc, category, ref_type, ref_id)


# ─────────────────────────────────────────────────────
# HPP
# ─────────────────────────────────────────────────────
def price_hpp(conn: sqlite3.Connection, price_id: int) -> Optional[dict]:
    """HPP per unit dari daftar Harga & HPP = total komponen + overhead."""
    p = conn.execute("SELECT id, produk_id, overhead, harga_jual FROM prices WHERE id=?",
                     (price_id,)).fetchone()
    if not p:
        return None
    comp = conn.execute("SELECT COALESCE(SUM(harga),0) AS t FROM price_components WHERE price_id=?",
                        (price_id,)).fetchone()["t"]
    return {"hpp": float(comp) + float(p["overhead"]), "produk_id": p["produk_id"],
            "harga_jual": float(p["harga_jual"])}
