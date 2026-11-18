#!/usr/bin/env python3
"""
sible_daftar.py — Daftar akun Sible Network langsung dari terminal VPS.

UNTUK SIAPA: pemilik akun itu sendiri, dijalankan di VPS-nya sendiri.
Script ini interaktif untuk SATU akun: email, password, dan kode OTP diketik
sendiri oleh pemilik akun di terminalnya. Password TIDAK disimpan; yang
disimpan hanya token sesi di tokens.json (mode 600) — format yang sama
dengan sible_keeper.py, jadi sesudah daftar bisa langsung --loop.

Alur API (hasil bedah bundle Web App Sible, REA ev_57936228… + ekstraksi
langsung — grafik REA tidak memuat endpoint auth, lihat README):
  POST /auth/register   {email, username?, password, referralCode?}
       -> {email, resendAfterSec, clock, referralWarning?}   (OTP dikirim)
  POST /auth/verify-otp {email, code, purpose:"verify_email"}
       -> {accessToken, refreshToken, user}
  Header wajib: X-Client-Type: web

Referral default: didinska (bisa diganti/dikosongkan saat prompt).
Kode referral dinormalkan server: trim + huruf besar (normalizeReferralInput).

Pagar: tidak ada mode batch/daftar massal. Satu jalankan = satu akun pemilik.
"""
import getpass
import json
import os
import sys
import urllib.request
import urllib.error

BASE = "https://prod.sible.network/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(HERE, "tokens.json")
HEADERS = {"X-Client-Type": "web", "Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


class ApiError(Exception):
    def __init__(self, code, message, http):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def call(method, path, body=None, token=None):
    h = dict(HEADERS)
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        err = payload.get("error") or {}
        raise ApiError(err.get("code", f"HTTP_{e.code}"),
                       err.get("message", str(e)), e.code)
    if payload.get("success") is False:
        err = payload.get("error") or {}
        raise ApiError(err.get("code", "API_ERROR"), err.get("message", "?"), 200)
    return payload.get("data", payload)


def norm_referral(code):
    """Samakan dengan normalizeReferralInput di app: trim, upper bila alfanumerik."""
    t = code.strip()
    return t.upper() if t.replace("-", "").replace("_", "").isalnum() else t


def main():
    print("=== Daftar Sible Network (akunmu sendiri, di VPS-mu sendiri) ===")
    if os.path.exists(TOKENS_FILE):
        ans = input("tokens.json sudah ada (sudah pernah login/daftar di folder ini). "
                    "Timpa? [y/N] ").strip().lower()
        if ans != "y":
            print("Batal. Kalau akunmu sudah ada, pakai: python3 sible_keeper.py --login")
            return

    email = input("Email kamu: ").strip().lower()
    if "@" not in email:
        print("Email tidak valid."); return
    username = input("Username (opsional, Enter = lewati): ").strip()
    pw1 = getpass.getpass("Buat password (min 8 karakter, ada huruf + angka): ")
    pw2 = getpass.getpass("Ulangi password: ")
    if (pw1 != pw2 or len(pw1) < 8
            or not any(c.isalpha() for c in pw1) or not any(c.isdigit() for c in pw1)):
        print("Password tidak cocok / tidak memenuhi aturan server "
              "(min 8 karakter, wajib huruf + angka). Jalankan lagi."); return
    ref_in = input("Kode referral [didinska]: ").strip()
    ref = norm_referral(ref_in) if ref_in else "DIDINSKA"

    body = {"email": email, "password": pw1}
    if username:
        body["username"] = username
    if ref:
        body["referralCode"] = ref

    print("Mengirim pendaftaran...")
    try:
        res = call("POST", "/auth/register", body)
    except ApiError as e:
        if e.code == "EMAIL_TAKEN":
            print("Email ini SUDAH terdaftar. Tidak perlu daftar lagi — jalankan:")
            print("  python3 sible_keeper.py --login")
        elif e.code == "USERNAME_TAKEN":
            print("Username sudah dipakai orang lain. Jalankan lagi dengan username lain.")
        elif e.code in ("TOO_MANY_REQUESTS", "HTTP_429"):
            print("Kena rate-limit server (5x/60 detik). Tunggu 1-2 menit, jalankan lagi.")
        else:
            print(f"Gagal: [{e.code}] {e.message}")
        return

    if res.get("referralWarning"):
        print(f"Catatan referral dari server: {res['referralWarning']}")
    print(f"Kode OTP dikirim ke {res.get('email', email)}. Cek inbox/spam.")
    code = input("Kode OTP 6 digit: ").strip()
    try:
        data = call("POST", "/auth/verify-otp",
                    {"email": res.get("email", email), "code": code,
                     "purpose": "verify_email"})
    except ApiError as e:
        print(f"Verifikasi gagal: [{e.code}] {e.message}")
        print("Akun mungkin sudah terbuat tapi belum terverifikasi — coba login lewat")
        print("Web App atau jalankan script ini lagi; bila EMAIL_TAKEN, pakai keeper --login.")
        return

    tokens = {"accessToken": data["accessToken"], "refreshToken": data["refreshToken"]}
    fd = os.open(TOKENS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f)
    user = data.get("user") or {}
    print(f"\n[OK] Daftar berhasil! Username: {user.get('username')} — token tersimpan (600).")

    # Coba nyalakan sesi mining pertama (best effort, bukan penentu sukses daftar)
    try:
        call("POST", "/mining/start", {}, token=tokens["accessToken"])
        print("[OK] Sesi mining pertama dinyalakan.")
    except ApiError as e:
        print(f"(mining/start: {e.code} — abaikan bila slot sudah terpakai)")
    print("\nLangkah berikutnya — nyalakan keeper otomatis:")
    print("  python3 sible_keeper.py --status")
    print("  screen -S sible  lalu:  python3 sible_keeper.py --loop")


if __name__ == "__main__":
    main()
