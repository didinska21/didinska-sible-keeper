#!/usr/bin/env python3
"""
Sible Network — single-account mining keeper (VPS).

Hasil reverse-engineering bundle web.sible.network (18 Nov 2026):
  API base : https://prod.sible.network/api/v1
  Auth     : JWT Bearer. POST /auth/login {identifier, password}
             -> SELALU lanjut OTP email (purpose="login")
             POST /auth/verify-otp {email, code, purpose}
             -> {accessToken, refreshToken, user}
             POST /auth/refresh {refreshToken} -> token BARU (rotasi;
             token lama mati, error sesi: SESSION_CHANGED / TOKEN_INVALID)
  Mining   : GET  /mining/status  (slotStartsAt, slotEndsAt, serverTime,
             slotsUsedToday, slotsPerDay, currentHourlyReward,
             currentSessionAmount, totalAmount, session{isRunning,endsAt},
             canClaim, canWatchAd)
             POST /mining/start   (error wajar: MINING_SLOT_ALREADY_USED)
             POST /mining/claim   -> {claimId, status:"pending"}
             GET  /mining/claim/<claimId>  (poll 0.5/1/2/4 dtk ...)
  Header   : X-Client-Type: web

Pagar (sengaja dikunci di kode):
  - HANYA 1 akun (akun Bos sendiri). Tidak ada multi-akun.
  - TIDAK memanggil /mining/ad (boost iklan) — itu bukan mining.
  - TIDAK menyentuh /reward-tasks (follow/posting/invite bukan urusan script).
  - Password TIDAK PERNAH disimpan. Login interaktif sekali di terminal VPS
    (getpass + OTP diketik Bos), sesudah itu yang disimpan hanya token
    di tokens.json (mode 600). Token ROTASI tersimpan ulang tiap refresh.
  - Berhenti total bila server menjawab ACCOUNT_BANNED / SESSION_CHANGED
    berulang — jangan dilawan.

Pakai:
  python3 sible_keeper.py --login     # sekali saja, interaktif (email+pass+OTP)
  python3 sible_keeper.py --status    # read-only: tampilkan status mining
  python3 sible_keeper.py --once      # 1 putaran: claim bila bisa, start bila idle
  python3 sible_keeper.py --loop      # jalan terus, tidur sampai slot berakhir
"""
import argparse, getpass, json, os, sys, time
import urllib.request, urllib.error

BASE = "https://prod.sible.network/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(HERE, "tokens.json")
HEADERS = {"X-Client-Type": "web", "Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
CLAIM_POLL_DELAYS = [0.5, 1, 2, 4, 8, 15, 30]


class ApiError(Exception):
    def __init__(self, code, message, http):
        super().__init__(f"{code}: {message} (HTTP {http})")
        self.code, self.http = code, http


def call(method, path, body=None, token=None, timeout=30):
    h = dict(HEADERS)
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        err = payload.get("error") or {}
        raise ApiError(err.get("code", "HTTP_ERROR"), err.get("message", str(e)), e.code)
    if payload.get("success") is False:
        err = payload.get("error") or {}
        raise ApiError(err.get("code", "API_ERROR"), err.get("message", "?"), 200)
    return payload.get("data", payload)


def save_tokens(tokens):
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tokens, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKENS_FILE)


def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE) as f:
        return json.load(f)


class Keeper:
    def __init__(self):
        self.tokens = load_tokens()
        if not self.tokens:
            sys.exit("tokens.json belum ada — jalankan: python3 sible_keeper.py --login")

    def refresh(self):
        rt = self.tokens.get("refreshToken")
        if not rt:
            sys.exit("refreshToken tidak ada di tokens.json — login ulang dengan --login")
        data = call("POST", "/auth/refresh", {"refreshToken": rt})
        self.tokens = {"accessToken": data["accessToken"],
                       "refreshToken": data["refreshToken"]}
        save_tokens(self.tokens)
        print("[auth] token di-refresh & disimpan (rotasi).")

    def authed(self, method, path, body=None):
        try:
            return call(method, path, body, token=self.tokens["accessToken"])
        except ApiError as e:
            if e.code in ("TOKEN_INVALID", "SESSION_CHANGED") or e.http == 401:
                print(f"[auth] access token ditolak ({e.code}) — refresh sekali...")
                self.refresh()
                return call(method, path, body, token=self.tokens["accessToken"])
            raise

    def status(self):
        return self.authed("GET", "/mining/status")

    def settle_claim(self):
        claim = self.authed("POST", "/mining/claim")
        cid, st = claim.get("claimId"), claim.get("status")
        print(f"[claim] dibuat id={cid} status={st}")
        for d in CLAIM_POLL_DELAYS:
            if st != "pending":
                break
            time.sleep(d)
            got = self.authed("GET", f"/mining/claim/{cid}")
            st = got.get("status", st)
            print(f"[claim] poll -> {st}")
        return st

    def once(self):
        st = self.status()
        sess = st.get("session") or {}
        print(f"[status] saldo={st.get('totalAmount')} sesi_ini={st.get('currentSessionAmount')} "
              f"rate={st.get('currentHourlyReward')}/jam slot={st.get('slotsUsedToday')}/{st.get('slotsPerDay')} "
              f"running={sess.get('isRunning')} canClaim={st.get('canClaim')} slot_berakhir={st.get('slotEndsAt')}")
        if st.get("canClaim"):
            out = self.settle_claim()
            print(f"[claim] hasil akhir: {out}")
            st = self.status()
            sess = st.get("session") or {}
        if not sess.get("isRunning"):
            try:
                self.authed("POST", "/mining/start")
                print("[mining] sesi BARU dimulai.")
            except ApiError as e:
                if e.code == "MINING_SLOT_ALREADY_USED":
                    print("[mining] slot hari ini sudah terpakai — tidak ada yang dimulai.")
                else:
                    raise
            st = self.status()
        return st

    def loop(self):
        while True:
            try:
                st = self.once()
            except ApiError as e:
                if e.code == "ACCOUNT_BANNED":
                    sys.exit("[STOP] ACCOUNT_BANNED dari server — script berhenti total.")
                print(f"[warn] API error {e.code} — tidur 300 dtk lalu coba lagi.")
                time.sleep(300)
                continue
            ends = st.get("slotEndsAt")
            wait = 900
            if ends:
                try:
                    end_ms = time.mktime(time.strptime(ends, "%Y-%m-%dT%H:%M:%S.%fZ")) - time.timezone
                    wait = max(60, int(end_ms - time.time()) + 15)
                except Exception:
                    pass
            print(f"[loop] tidur {wait} dtk (sampai slot berakhir + buffer).")
            time.sleep(wait)


def do_login():
    email = input("Email akun Sible: ").strip()
    password = getpass.getpass("Password (tidak disimpan): ")
    r = call("POST", "/auth/login", {"identifier": email, "password": password})
    print(f"OTP dikirim ke {r.get('email', email)} — cek inbox (resend setelah {r.get('resendAfterSec')} dtk bila perlu).")
    code = input("Kode OTP 6 digit: ").strip()
    data = call("POST", "/auth/verify-otp",
                {"email": r.get("email", email), "code": code, "purpose": "login"})
    save_tokens({"accessToken": data["accessToken"], "refreshToken": data["refreshToken"]})
    user = data.get("user") or {}
    print(f"[OK] Login berhasil sebagai {user.get('username')} — token tersimpan di tokens.json (600).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    if a.login:
        do_login()
    elif a.status:
        k = Keeper()
        print(json.dumps(k.status(), indent=2))
    elif a.loop:
        Keeper().loop()
    else:
        Keeper().once()
