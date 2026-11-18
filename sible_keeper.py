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
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))
TTY = sys.stdout.isatty()
C = {"reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "green": "\033[32m",
     "cyan": "\033[36m", "yellow": "\033[33m", "red": "\033[31m"} if TTY else {
     k: "" for k in ("reset", "bold", "dim", "green", "cyan", "yellow", "red")}


def now_wib():
    return datetime.now(WIB).strftime("%H:%M:%S")


def log(msg):
    print(f"{C['dim']}[{now_wib()} WIB]{C['reset']} {msg}", flush=True)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def fmt_dur(sec):
    sec = max(0, int(sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def bar(pct, width=26):
    pct = min(1.0, max(0.0, pct))
    fill = int(round(pct * width))
    return "█" * fill + "░" * (width - fill)


def fmt_panel(st):
    """Panel status mining — murni tampilan, data apa adanya dari /mining/status."""
    sess = st.get("session") or {}
    start, end, srv = parse_iso(st.get("slotStartsAt")), parse_iso(st.get("slotEndsAt")), parse_iso(st.get("serverTime"))
    pct, sisa = 0.0, None
    if start and end and srv and end > start:
        pct = (srv - start).total_seconds() / (end - start).total_seconds()
        sisa = (end - srv).total_seconds()
    running = bool(sess.get("isRunning"))
    state = f"{C['green']}● MINING JALAN{C['reset']}" if running else (
        f"{C['yellow']}● MENUNGGU CLAIM{C['reset']}" if st.get("canClaim") else f"{C['red']}● IDLE{C['reset']}")
    rows = [
        ("Saldo total", f"{C['bold']}{st.get('totalAmount')} SIBLE{C['reset']}"),
        ("Sesi ini", f"{st.get('currentSessionAmount')} SIBLE"),
        ("Rate", f"{st.get('currentHourlyReward')}/jam"),
        ("Slot hari ini", f"{st.get('slotsUsedToday')}/{st.get('slotsPerDay')}"),
        ("Status", state),
        ("Slot berakhir", f"{end.astimezone(WIB).strftime('%H:%M:%S')} WIB" if end else "-"),
    ]
    if sisa is not None:
        rows.append(("Sisa slot", fmt_dur(sisa)))
    w = 58
    out = [f"{C['cyan']}╭{'─' * w}╮{C['reset']}",
           f"{C['cyan']}│{C['reset']} {C['bold']}⛏  SIBLE KEEPER — {now_wib()} WIB{C['reset']}{' ' * (w - 26)}{C['cyan']}│{C['reset']}",
           f"{C['cyan']}├{'─' * w}┤{C['reset']}"]
    for k, v in rows:
        plain = v.replace("\033", "")
        out.append(f"{C['cyan']}│{C['reset']}  {k:<14}: {v}{' ' * max(0, w - 18 - len(v))}{C['cyan']}│{C['reset']}")
    out.append(f"{C['cyan']}│{C['reset']}  Slot {bar(pct)} {pct * 100:5.1f}%{' ' * (w - 40)}{C['cyan']}│{C['reset']}")
    out.append(f"{C['cyan']}╰{'─' * w}╯{C['reset']}")
    return "\n".join(out)

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
        log("🔑 token di-refresh & disimpan (rotasi).")

    def authed(self, method, path, body=None):
        try:
            return call(method, path, body, token=self.tokens["accessToken"])
        except ApiError as e:
            if e.code in ("TOKEN_INVALID", "SESSION_CHANGED") or e.http == 401:
                log(f"🔑 access token ditolak ({e.code}) — refresh sekali...")
                self.refresh()
                return call(method, path, body, token=self.tokens["accessToken"])
            raise

    def status(self):
        return self.authed("GET", "/mining/status")

    def settle_claim(self):
        claim = self.authed("POST", "/mining/claim")
        cid, st = claim.get("claimId"), claim.get("status")
        log(f"🎁 claim dibuat id={cid} status={st}")
        for d in CLAIM_POLL_DELAYS:
            if st != "pending":
                break
            time.sleep(d)
            got = self.authed("GET", f"/mining/claim/{cid}")
            st = got.get("status", st)
            log(f"🎁 claim poll → {st}")
        return st

    def once(self):
        st = self.status()
        print(fmt_panel(st))
        sess = st.get("session") or {}
        if st.get("canClaim"):
            out = self.settle_claim()
            log(f"🎁 claim selesai: {out}")
            st = self.status()
            sess = st.get("session") or {}
        if not sess.get("isRunning"):
            try:
                self.authed("POST", "/mining/start")
                log("⛏  sesi BARU dimulai.")
            except ApiError as e:
                if e.code == "MINING_SLOT_ALREADY_USED":
                    log("⛏  slot hari ini sudah terpakai — tidak ada yang dimulai.")
                else:
                    raise
            st = self.status()
            print(fmt_panel(st))
        return st

    def loop(self):
        while True:
            try:
                st = self.once()
            except ApiError as e:
                if e.code == "ACCOUNT_BANNED":
                    sys.exit("[STOP] ACCOUNT_BANNED dari server — script berhenti total.")
                log(f"⚠️  API error {e.code} — tidur 300 dtk lalu coba lagi.")
                time.sleep(300)
                continue
            ends = parse_iso(st.get("slotEndsAt"))
            wait = 900
            if ends:
                wait = max(60, int((ends - datetime.now(timezone.utc)).total_seconds()) + 15)
            log(f"💤 tidur {fmt_dur(wait)} (sampai slot berakhir + buffer).")
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
    ap.add_argument("--json", action="store_true", help="dengan --status: tampilkan JSON mentah")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    if a.login:
        do_login()
    elif a.status:
        k = Keeper()
        st = k.status()
        print(json.dumps(st, indent=2) if a.json else fmt_panel(st))
    elif a.loop:
        Keeper().loop()
    else:
        Keeper().once()
