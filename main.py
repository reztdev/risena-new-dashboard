# main.py — BatikCraft Backend API (FastAPI + SQLite)
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import get_conn, init_db, fmt_date_id
from datetime import datetime

from auth import router as auth_router
from consignment import router as consignment_router
from printing import router as printing_router
from production import router as production_router
from reports import router as reports_router
from consignment import hitung_rekomendasi
from ledger import (apply_stock, undo_ref, log_movement, cashflow_add,
                    cashflow_remove, price_hpp, now_iso)
                 

# ─────────────────────────────────────────────────────
# LIFESPAN — inisialisasi DB saat startup
# ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("🪡  Risena Collection siap dijalankan.")
    yield


app = FastAPI(title="Risena API", version="2.1", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(consignment_router)
app.include_router(printing_router)
app.include_router(production_router)
app.include_router(reports_router)

PUBLIC_DIR = Path(__file__).parent / "public"


# ─────────────────────────────────────────────────────
# PYDANTIC MODELS (request body)
# ─────────────────────────────────────────────────────
class ProductIn(BaseModel):
    kode:      str  = ""
    nama:      str
    kategori:  str  = "Lainnya"
    stok:      int  = 0
    minStok:   int  = Field(5, alias="minStok")
    satuan:    str  = "pcs"
    deskripsi: str  = ""

    model_config = {"populate_by_name": True}


class MaterialIn(BaseModel):
    kode:        str   = ""
    nama:        str
    kategori:    str   = "Lainnya"
    stok:        float = 0
    minStok:     float = Field(5, alias="minStok")
    satuan:      str   = "meter"
    hargaSatuan: float = Field(0, alias="hargaSatuan")
    supplier:    str   = ""
    catatan:     str   = ""

    model_config = {"populate_by_name": True}


class StokAdjIn(BaseModel):
    type:       str   = "in"   # "in" = stok masuk, "out" = stok keluar
    jumlah:     float = 0
    keterangan: str   = ""
    # Opsional, hanya untuk stok MASUK (restok/pembelian):
    # total uang yang dibayar. Bila diisi → harga satuan bahan ikut
    # diperbarui ke harga beli terakhir & pengeluaran masuk Arus Kas.
    totalHarga: float = 0
    supplier:   str   = ""


class ComponentIn(BaseModel):
    nama:  str
    harga: float = 0


class PriceIn(BaseModel):
    produkId:   int
    overhead:   float = 0
    hargaJual:  float = 0
    components: list[ComponentIn] = []


class OrderItemIn(BaseModel):
    priceId:  Optional[int] = None
    nama:     str
    harga:    float
    qty:      int
    subtotal: float


class OrderIn(BaseModel):
    id:       str
    customer: str   = "Umum"
    date:     str
    dateStr:  str   = ""
    subtotal: float = 0
    discount: float = 0
    total:    float = 0
    note:     str   = ""
    items:    list[OrderItemIn] = []


class CashflowIn(BaseModel):
    id:       Optional[str] = None
    type:     str  = "in"
    date:     str
    dateStr:  str  = ""
    desc:     str
    category: str  = "Lain-lain"
    amount:   float


# ─────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────
def _fmt_date_from_iso(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return fmt_date_id(dt)
    except Exception:
        return iso


def _material_row(r) -> dict:
    return {
        "id":          r["id"],
        "kode":        r["kode"],
        "nama":        r["nama"],
        "kategori":    r["kategori"],
        "stok":        r["stok"],
        "minStok":     r["min_stok"],
        "satuan":      r["satuan"],
        "hargaSatuan": r["harga_satuan"],
        "supplier":    r["supplier"],
        "catatan":     r["catatan"],
    }


# ═══════════════════════════════════════════════════════════
# PRODUCTS
# ═══════════════════════════════════════════════════════════

@app.get("/api/products")
def get_products() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    return [
        {
            "id":        r["id"],
            "kode":      r["kode"],
            "nama":      r["nama"],
            "kategori":  r["kategori"],
            "stok":      r["stok"],
            "minStok":   r["min_stok"],
            "satuan":    r["satuan"],
            "deskripsi": r["deskripsi"],
        }
        for r in rows
    ]


@app.post("/api/products", status_code=status.HTTP_201_CREATED)
def create_product(body: ProductIn) -> dict:
    if not body.nama.strip():
        raise HTTPException(400, "Nama produk wajib diisi")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO products (kode,nama,kategori,stok,min_stok,satuan,deskripsi) "
            "VALUES (?,?,?,?,?,?,?)",
            (body.kode, body.nama, body.kategori, body.stok,
             body.minStok, body.satuan, body.deskripsi),
        )
        new_id = cur.lastrowid
        if body.stok > 0:
            log_movement(conn, "product", new_id, body.nama, body.stok, body.stok,
                         "initial", str(new_id), "Stok awal")
        conn.commit()
    return {
        "id": new_id, "kode": body.kode, "nama": body.nama,
        "kategori": body.kategori, "stok": body.stok, "minStok": body.minStok,
        "satuan": body.satuan, "deskripsi": body.deskripsi,
    }


@app.put("/api/products/{product_id}")
def update_product(product_id: int, body: ProductIn) -> dict:
    with get_conn() as conn:
        old = conn.execute("SELECT stok FROM products WHERE id=?", (product_id,)).fetchone()
        if old is not None and body.stok != old["stok"]:
            log_movement(conn, "product", product_id, body.nama, body.stok - old["stok"],
                         body.stok, "adjust", f"edit-{product_id}", "Koreksi stok manual")
        conn.execute(
            "UPDATE products SET kode=?,nama=?,kategori=?,stok=?,min_stok=?,satuan=?,deskripsi=? "
            "WHERE id=?",
            (body.kode, body.nama, body.kategori, body.stok,
             body.minStok, body.satuan, body.deskripsi, product_id),
        )
        conn.commit()
    return {
        "id": product_id, "kode": body.kode, "nama": body.nama,
        "kategori": body.kategori, "stok": body.stok, "minStok": body.minStok,
        "satuan": body.satuan, "deskripsi": body.deskripsi,
    }


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# MATERIALS (Stok Bahan Baku)
# ═══════════════════════════════════════════════════════════

@app.get("/api/materials")
def get_materials() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM materials ORDER BY id").fetchall()
    return [_material_row(r) for r in rows]


@app.post("/api/materials", status_code=status.HTTP_201_CREATED)
def create_material(body: MaterialIn) -> dict:
    if not body.nama.strip():
        raise HTTPException(400, "Nama bahan wajib diisi")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO materials (kode,nama,kategori,stok,min_stok,satuan,harga_satuan,supplier,catatan) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (body.kode, body.nama, body.kategori, body.stok,
             body.minStok, body.satuan, body.hargaSatuan, body.supplier, body.catatan),
        )
        new_id = cur.lastrowid
        if body.stok > 0:
            log_movement(conn, "material", new_id, body.nama, body.stok, body.stok,
                         "initial", str(new_id), "Stok awal", body.hargaSatuan)
        conn.commit()
        row = conn.execute("SELECT * FROM materials WHERE id=?", (new_id,)).fetchone()
    return _material_row(row)


@app.put("/api/materials/{material_id}")
def update_material(material_id: int, body: MaterialIn) -> dict:
    with get_conn() as conn:
        old = conn.execute("SELECT stok FROM materials WHERE id=?", (material_id,)).fetchone()
        if old is not None and abs(body.stok - old["stok"]) > 1e-9:
            log_movement(conn, "material", material_id, body.nama, body.stok - old["stok"],
                         body.stok, "adjust", f"edit-{material_id}", "Koreksi stok manual",
                         body.hargaSatuan)
        conn.execute(
            "UPDATE materials SET kode=?,nama=?,kategori=?,stok=?,min_stok=?,satuan=?,harga_satuan=?,supplier=?,catatan=? "
            "WHERE id=?",
            (body.kode, body.nama, body.kategori, body.stok,
             body.minStok, body.satuan, body.hargaSatuan, body.supplier, body.catatan,
             material_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    return _material_row(row)


@app.delete("/api/materials/{material_id}")
def delete_material(material_id: int) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
        conn.commit()
    return {"ok": True}


@app.post("/api/materials/{material_id}/stok")
def adjust_material_stok(material_id: int, body: StokAdjIn) -> dict:
    """
    Tambah atau kurangi stok bahan baku.

    Stok MASUK + totalHarga diisi  →  dianggap PEMBELIAN/RESTOK:
      • stok bertambah
      • harga satuan bahan = totalHarga / jumlah  (harga beli terakhir)
      • tercatat di riwayat pembelian & kartu stok
      • pengeluaran otomatis masuk Arus Kas (kategori 'Bahan Baku')
      • bila harga berubah, dihitung produk mana yang marginnya terdampak
    Selain itu hanya mengubah stok (tetap tercatat di kartu stok).
    """
    if body.jumlah <= 0:
        raise HTTPException(400, "Jumlah harus lebih dari 0")
    if body.totalHarga < 0:
        raise HTTPException(400, "Total harga tidak boleh negatif")

    with get_conn() as conn:
        m = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if not m:
            raise HTTPException(404, "Bahan tidak ditemukan")

        harga_lama = float(m["harga_satuan"])
        out: dict = {"hargaSatuan": harga_lama, "hargaLama": harga_lama,
                     "naikPersen": 0, "cashflowId": None, "purchaseId": None,
                     "rekomendasi": []}

        if body.type == "in" and body.totalHarga > 0:
            harga_baru = round(body.totalHarga / body.jumlah, 2)
            tgl = now_iso()
            cur = conn.execute(
                "INSERT INTO material_purchases (material_id,nama_material,tanggal,jumlah,"
                "total_harga,harga_satuan,harga_sebelumnya,supplier,catatan) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (material_id, m["nama"], tgl, body.jumlah, body.totalHarga, harga_baru,
                 harga_lama, body.supplier or m["supplier"], body.keterangan),
            )
            pid = cur.lastrowid
            jml = f"{body.jumlah:g}"
            cf_id = cashflow_add(conn, "out", body.totalHarga,
                                 f"Beli {m['nama']} {jml} {m['satuan']}",
                                 "Bahan Baku", "purchase", str(pid), date_iso=tgl)
            conn.execute("UPDATE material_purchases SET cashflow_id=? WHERE id=?", (cf_id, pid))
            res = apply_stock(conn, "material", material_id, body.jumlah, "purchase",
                              str(pid), body.keterangan or "Restok", harga_baru)
            conn.execute("UPDATE materials SET harga_satuan=?, supplier=? WHERE id=?",
                         (harga_baru, body.supplier or m["supplier"], material_id))
            out.update(hargaSatuan=harga_baru, cashflowId=cf_id, purchaseId=pid)
            if harga_lama > 0 and abs(harga_baru - harga_lama) > 1e-9:
                naik_nominal, naik_persen, rek = hitung_rekomendasi(
                    conn, m["nama"], harga_lama, harga_baru, 30.0)
                out.update(naikPersen=naik_persen, rekomendasi=rek)
        else:
            signed = body.jumlah if body.type == "in" else -body.jumlah
            res = apply_stock(conn, "material", material_id, signed, "adjust",
                              f"adj-{int(time.time() * 1000)}",
                              body.keterangan or ("Stok masuk" if signed > 0 else "Stok keluar"),
                              harga_lama)
        conn.commit()
    out["stok"] = res["new"]
    return out


# ═══════════════════════════════════════════════════════════
# PRICES (Harga & HPP)
# ═══════════════════════════════════════════════════════════

@app.get("/api/prices")
def get_prices() -> list[dict]:
    with get_conn() as conn:
        price_rows = conn.execute("SELECT * FROM prices ORDER BY id").fetchall()
        result = []
        for p in price_rows:
            comps = conn.execute(
                "SELECT nama, harga FROM price_components WHERE price_id=?", (p["id"],)
            ).fetchall()
            result.append({
                "id":         p["id"],
                "produkId":   p["produk_id"],
                "overhead":   p["overhead"],
                "hargaJual":  p["harga_jual"],
                "components": [{"nama": c["nama"], "harga": c["harga"]} for c in comps],
            })
    return result


@app.post("/api/prices", status_code=status.HTTP_201_CREATED)
def create_price(body: PriceIn) -> dict:
    if not body.produkId:
        raise HTTPException(400, "Produk wajib dipilih")
    comps = [c for c in body.components if c.nama.strip()]
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO prices (produk_id,overhead,harga_jual) VALUES (?,?,?)",
            (body.produkId, body.overhead, body.hargaJual),
        )
        pid = cur.lastrowid
        for c in comps:
            conn.execute(
                "INSERT INTO price_components (price_id,nama,harga) VALUES (?,?,?)",
                (pid, c.nama, c.harga),
            )
        hpp = sum(c.harga for c in comps) + body.overhead
        conn.execute(
            "INSERT INTO price_history (price_id,produk_id,harga_jual_lama,harga_jual_baru,hpp,tanggal) "
            "VALUES (?,?,?,?,?,?)",
            (pid, body.produkId, 0, body.hargaJual, hpp, now_iso()),
        )
        conn.commit()
    return {
        "id": pid, "produkId": body.produkId,
        "overhead": body.overhead, "hargaJual": body.hargaJual,
        "components": [{"nama": c.nama, "harga": c.harga} for c in comps],
    }


@app.put("/api/prices/{price_id}")
def update_price(price_id: int, body: PriceIn) -> dict:
    comps = [c for c in body.components if c.nama.strip()]
    with get_conn() as conn:
        old = conn.execute("SELECT harga_jual FROM prices WHERE id=?", (price_id,)).fetchone()
        if old is not None and abs(old["harga_jual"] - body.hargaJual) > 1e-9:
            hpp = sum(c.harga for c in comps) + body.overhead
            conn.execute(
                "INSERT INTO price_history (price_id,produk_id,harga_jual_lama,harga_jual_baru,hpp,tanggal) "
                "VALUES (?,?,?,?,?,?)",
                (price_id, body.produkId, old["harga_jual"], body.hargaJual, hpp, now_iso()),
            )
        conn.execute(
            "UPDATE prices SET produk_id=?,overhead=?,harga_jual=? WHERE id=?",
            (body.produkId, body.overhead, body.hargaJual, price_id),
        )
        conn.execute("DELETE FROM price_components WHERE price_id=?", (price_id,))
        for c in comps:
            conn.execute(
                "INSERT INTO price_components (price_id,nama,harga) VALUES (?,?,?)",
                (price_id, c.nama, c.harga),
            )
        conn.commit()
    return {
        "id": price_id, "produkId": body.produkId,
        "overhead": body.overhead, "hargaJual": body.hargaJual,
        "components": [{"nama": c.nama, "harga": c.harga} for c in comps],
    }


@app.get("/api/prices/{price_id}/history")
def price_history(price_id: int) -> list[dict]:
    """Riwayat perubahan harga jual sebuah produk (terbaru di atas)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE price_id=? ORDER BY id DESC", (price_id,)
        ).fetchall()
    return [{"tanggal": r["tanggal"], "hargaJualLama": r["harga_jual_lama"],
             "hargaJualBaru": r["harga_jual_baru"], "hpp": r["hpp"]} for r in rows]


@app.delete("/api/prices/{price_id}")
def delete_price(price_id: int) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM prices WHERE id=?", (price_id,))
        conn.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# ORDERS
# ═══════════════════════════════════════════════════════════

@app.get("/api/orders")
def get_orders() -> list[dict]:
    with get_conn() as conn:
        orders = conn.execute("SELECT * FROM orders ORDER BY date DESC").fetchall()
        result = []
        for o in orders:
            items = conn.execute(
                "SELECT * FROM order_items WHERE order_id=?", (o["id"],)
            ).fetchall()
            result.append({
                "id":       o["id"],
                "customer": o["customer"],
                "date":     o["date"],
                "dateStr":  o["date_str"],
                "subtotal": o["subtotal"],
                "discount": o["discount"],
                "total":    o["total"],
                "note":     o["note"],
                "items": [
                    {
                        "priceId":  it["price_id"],
                        "nama":     it["nama"],
                        "harga":    it["harga"],
                        "qty":      it["qty"],
                        "subtotal": it["subtotal"],
                        "hpp":      it["hpp"],
                    }
                    for it in items
                ],
            })
    return result


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(body: OrderIn) -> dict:
    """
    Simpan order. Dalam 1 transaksi database:
      • order + item (membawa HPP per unit saat itu → laba lama tidak berubah
        walau harga bahan naik di kemudian hari)
      • stok produk jadi berkurang (tercatat di kartu stok)
      • pemasukan otomatis masuk Arus Kas, terhubung ke order ini
    Stok tidak pernah menolak penjualan; bila stok kurang, stok jadi 0 dan
    muncul peringatan agar stok dicek.
    """
    if not body.id or not body.items:
        raise HTTPException(400, "Order tidak valid")

    date_str = body.dateStr or _fmt_date_from_iso(body.date)
    customer = body.customer or "Umum"
    warnings: list[str] = []
    stok_map: dict[int, int] = {}

    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM orders WHERE id=?", (body.id,)).fetchone():
            raise HTTPException(409, f"Order {body.id} sudah ada")
        conn.execute(
            "INSERT INTO orders (id,customer,date,date_str,subtotal,discount,total,note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (body.id, customer, body.date, date_str,
             body.subtotal, body.discount, body.total, body.note),
        )
        for it in body.items:
            hpp, produk_id = 0.0, None
            if it.priceId:
                info = price_hpp(conn, it.priceId)
                if info:
                    hpp, produk_id = info["hpp"], info["produk_id"]
            conn.execute(
                "INSERT INTO order_items (order_id,price_id,nama,harga,qty,subtotal,hpp,hpp_est) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (body.id, it.priceId, it.nama, it.harga, it.qty, it.subtotal, hpp),
            )
            if produk_id:
                r = apply_stock(conn, "product", produk_id, -it.qty, "order", body.id,
                                f"Order {body.id} · {customer}", hpp)
                if r:
                    stok_map[produk_id] = r["new"]
                    if r["shortfall"] > 0:
                        warnings.append(
                            f"Stok '{r['nama']}' kurang {int(r['shortfall'])} pcs — "
                            f"stok jadi 0, mohon cek stok.")
        cf_id = cashflow_add(conn, "in", body.total, f"Penjualan - {customer}",
                             "Penjualan", "order", body.id,
                             date_iso=body.date, date_str=date_str)
        conn.commit()
    return {"ok": True, "id": body.id, "cashflowId": cf_id,
            "stok": stok_map, "warnings": warnings}


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str) -> dict:
    """
    Batalkan order: stok produk dikembalikan dan pemasukan di Arus Kas
    yang terhubung ke order ini ikut dihapus.
    (Order lama sebelum update ini tidak pernah mengurangi stok, jadi
    stoknya memang tidak dikembalikan.)
    """
    with get_conn() as conn:
        o = conn.execute("SELECT customer, date, total FROM orders WHERE id=?",
                         (order_id,)).fetchone()
        undo_ref(conn, "order", order_id)
        removed = cashflow_remove(conn, "order", order_id)
        if o and not removed:
            # order lama: kas-nya belum terhubung. Cocokkan PERSIS (tanggal+nama+nominal)
            # dan hapus satu baris saja, supaya kas tidak tertinggal.
            conn.execute(
                "DELETE FROM cashflows WHERE id = (SELECT id FROM cashflows "
                "WHERE ref_type='' AND type='in' AND category='Penjualan' "
                "AND amount=? AND date=? AND desc_text=? LIMIT 1)",
                (o["total"], o["date"], f"Penjualan - {o['customer']}"),
            )
        conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
        conn.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# CASHFLOW
# ═══════════════════════════════════════════════════════════

@app.get("/api/cashflows")
def get_cashflows() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cashflows ORDER BY date DESC").fetchall()
    return [
        {
            "id":       r["id"],
            "type":     r["type"],
            "date":     r["date"],
            "dateStr":  r["date_str"],
            "desc":     r["desc_text"],
            "category": r["category"],
            "amount":   r["amount"],
            "refType":  r["ref_type"],
            "refId":    r["ref_id"],
        }
        for r in rows
    ]


@app.get("/api/stock-movements")
def get_stock_movements(type: str = "", itemId: int = 0, limit: int = 200) -> list[dict]:
    """Kartu stok: riwayat stok masuk/keluar. Filter: type=product|material, itemId."""
    q, args = "SELECT * FROM stock_movements WHERE 1=1", []
    if type in ("product", "material"):
        q += " AND item_type=?"; args.append(type)
    if itemId:
        q += " AND item_id=?"; args.append(itemId)
    q += " ORDER BY id DESC LIMIT ?"; args.append(max(1, min(limit, 1000)))
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    return [{"id": r["id"], "tanggal": r["tanggal"], "itemType": r["item_type"],
             "itemId": r["item_id"], "nama": r["nama"], "qty": r["qty"],
             "stokSesudah": r["stok_sesudah"], "unitCost": r["unit_cost"],
             "refType": r["ref_type"], "refId": r["ref_id"], "catatan": r["catatan"]}
            for r in rows]


@app.post("/api/cashflows", status_code=status.HTTP_201_CREATED)
def create_cashflow(body: CashflowIn) -> dict:
    if not body.desc.strip() or not body.amount:
        raise HTTPException(400, "Data tidak lengkap")

    cf_id    = body.id or f"CF-{int(time.time() * 1000)}"
    date_str = body.dateStr or _fmt_date_from_iso(body.date)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cashflows (id,type,date,date_str,desc_text,category,amount) "
            "VALUES (?,?,?,?,?,?,?)",
            (cf_id, body.type, body.date, date_str,
             body.desc, body.category, body.amount),
        )
        conn.commit()
    return {
        "id": cf_id, "type": body.type, "date": body.date,
        "dateStr": date_str, "desc": body.desc,
        "category": body.category, "amount": body.amount,
    }


@app.delete("/api/cashflows/{cashflow_id}")
def delete_cashflow(cashflow_id: str) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM cashflows WHERE id=?", (cashflow_id,))
        conn.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# STATIC FILES — sajikan frontend dari folder public/
# ═══════════════════════════════════════════════════════════

if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")

@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    """Semua request non-API diarahkan ke index.html (SPA fallback)."""
    index = PUBLIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend tidak ditemukan"}, status_code=404)


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

