# reports.py — Laporan Laba bulanan & peringatan margin
# ─────────────────────────────────────────────────────────────────────────
# Laba dihitung dari data yang sudah saling terhubung:
#   Pendapatan  = order (total setelah diskon) + konsinyasi bersih (setelah komisi)
#   HPP terjual = Σ (HPP per unit yang DISIMPAN saat order × qty)  + modal konsinyasi
#   Laba kotor  = Pendapatan − HPP terjual
#   Laba bersih = Laba kotor − biaya operasional + pemasukan lain
# Pembelian bahan baku TIDAK dipotong langsung sebagai biaya — nilainya sudah
# masuk lewat HPP saat barangnya terjual (kalau tidak, bahan dihitung dua kali).
# ─────────────────────────────────────────────────────────────────────────
from datetime import datetime, timedelta

from fastapi import APIRouter

from database import get_conn

router = APIRouter(prefix="/api", tags=["laporan"])

# kategori kas keluar yang BUKAN biaya operasional
_BUKAN_BIAYA = {"Bahan Baku", "Modal"}


def _local_dt(iso: str, tz_minutes: int):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None) - (dt.utcoffset() or timedelta(0))
    return dt + timedelta(minutes=tz_minutes)


def _ym(iso: str, tz_minutes: int) -> str:
    dt = _local_dt(iso, tz_minutes)
    return f"{dt.year}-{dt.month:02d}" if dt else ""


def _ymd(iso: str, tz_minutes: int) -> str:
    dt = _local_dt(iso, tz_minutes)
    return dt.strftime("%Y-%m-%d") if dt else ""


@router.get("/reports/profit")
def profit_report(month: str = "", tz: int = 0, batas: float = 30.0) -> dict:
    """
    Laporan laba 1 bulan.
      month = 'YYYY-MM' (kosong = bulan ini)
      tz    = selisih menit zona waktu dari UTC (WIB = 420)
      batas = ambang margin rendah (%) untuk daftar peringatan
    """
    if not month:
        now = datetime.utcnow() + timedelta(minutes=tz)
        month = f"{now.year}-{now.month:02d}"

    with get_conn() as conn:
        orders = [o for o in conn.execute("SELECT * FROM orders").fetchall()
                  if _ym(o["date"], tz) == month]
        order_ids = {o["id"] for o in orders}
        pendapatan_order = sum(o["total"] for o in orders)

        hpp_order, perkiraan = 0.0, 0
        for o in orders:
            for it in conn.execute("SELECT hpp, hpp_est, qty FROM order_items WHERE order_id=?",
                                   (o["id"],)).fetchall():
                hpp_order += it["hpp"] * it["qty"]
                perkiraan += 1 if it["hpp_est"] else 0

        cfs = [c for c in conn.execute("SELECT * FROM cashflows").fetchall()
               if _ym(c["date"], tz) == month]

        # ── konsinyasi (kas masuk saat batch selesai) ──
        pend_ks, hpp_ks, n_ks = 0.0, 0.0, 0
        for c in cfs:
            if c["ref_type"] == "consignment" and c["type"] == "in":
                n_ks += 1
                pend_ks += c["amount"]
                for it in conn.execute(
                        "SELECT qty_terjual, harga_modal FROM consignment_items WHERE batch_id=?",
                        (c["ref_id"],)).fetchall():
                    hpp_ks += it["qty_terjual"] * it["harga_modal"]

        # ── pemasukan lain: kas masuk manual selain penjualan/modal ──
        # Kas 'Penjualan' lama (sebelum kas terhubung ke order) dicocokkan ke
        # order berdasarkan tanggal+nominal agar tidak terhitung dua kali.
        order_keys = {}
        for o in orders:
            order_keys.setdefault((_ymd(o["date"], tz), round(o["total"])), 0)
            order_keys[(_ymd(o["date"], tz), round(o["total"]))] += 1
        pemasukan_lain, penjualan_manual = 0.0, 0.0
        for c in cfs:
            if c["type"] != "in" or c["ref_type"] in ("order", "consignment"):
                continue
            if c["category"] == "Modal":
                continue
            if c["category"] == "Penjualan":
                key = (_ymd(c["date"], tz), round(c["amount"]))
                if order_keys.get(key, 0) > 0:      # kas otomatis dari order lama
                    order_keys[key] -= 1
                    continue
                penjualan_manual += c["amount"]
            pemasukan_lain += c["amount"]

        # ── biaya operasional ──
        per_kat: dict[str, float] = {}
        pembelian_bahan = 0.0
        for c in cfs:
            if c["type"] != "out":
                continue
            if c["category"] == "Bahan Baku":
                pembelian_bahan += c["amount"]
            if c["category"] in _BUKAN_BIAYA:
                continue
            per_kat[c["category"]] = per_kat.get(c["category"], 0) + c["amount"]
        biaya_ops = sum(per_kat.values())

        # ── peringatan margin rendah (HPP & harga jual saat ini) ──
        margin_rendah = []
        for p in conn.execute(
                "SELECT p.id, p.overhead, p.harga_jual, pr.nama FROM prices p "
                "JOIN products pr ON pr.id = p.produk_id").fetchall():
            comp = conn.execute("SELECT COALESCE(SUM(harga),0) t FROM price_components WHERE price_id=?",
                                (p["id"],)).fetchone()["t"]
            hpp = comp + p["overhead"]
            if p["harga_jual"] > 0:
                mg = (p["harga_jual"] - hpp) / p["harga_jual"] * 100
                if mg < batas:
                    margin_rendah.append({
                        "nama": p["nama"], "hpp": round(hpp, 2),
                        "hargaJual": round(p["harga_jual"], 2),
                        "marginPersen": round(mg, 1),
                    })
        margin_rendah.sort(key=lambda x: x["marginPersen"])

    pendapatan = pendapatan_order + pend_ks
    hpp_total = hpp_order + hpp_ks
    laba_kotor = pendapatan - hpp_total
    laba_bersih = laba_kotor - biaya_ops + pemasukan_lain

    catatan = []
    if perkiraan:
        catatan.append(f"{perkiraan} item order lama memakai HPP perkiraan "
                       f"(HPP saat ini), karena dulu HPP belum disimpan per order.")
    if penjualan_manual:
        catatan.append("Ada kas 'Penjualan' manual yang tidak terhubung ke order; "
                       "dihitung sebagai pemasukan lain (tanpa HPP).")

    return {
        "month": month,
        "penjualan": {"pendapatan": round(pendapatan_order, 2), "hpp": round(hpp_order, 2),
                      "jumlahOrder": len(order_ids), "itemPerkiraan": perkiraan},
        "konsinyasi": {"pendapatanBersih": round(pend_ks, 2), "hpp": round(hpp_ks, 2),
                       "jumlahBatch": n_ks},
        "pemasukanLain": round(pemasukan_lain, 2),
        "biayaOperasional": {
            "total": round(biaya_ops, 2),
            "rincian": [{"kategori": k, "jumlah": round(v, 2)}
                        for k, v in sorted(per_kat.items(), key=lambda kv: -kv[1])],
        },
        "pembelianBahan": round(pembelian_bahan, 2),
        "ringkasan": {
            "pendapatan": round(pendapatan, 2),
            "hppTerjual": round(hpp_total, 2),
            "labaKotor": round(laba_kotor, 2),
            "marginKotorPersen": round(laba_kotor / pendapatan * 100, 1) if pendapatan else 0,
            "biayaOperasional": round(biaya_ops, 2),
            "labaBersih": round(laba_bersih, 2),
        },
        "marginRendah": margin_rendah,
        "batasMargin": batas,
        "catatan": catatan,
    }
