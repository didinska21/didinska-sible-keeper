# Sible Keeper — script VPS 1 akun

Temuan recon 18 Nov 2026 (bundle web.sible.network):
- API: `https://prod.sible.network/api/v1`, auth JWT Bearer, header `X-Client-Type: web`
- Login selalu OTP email; sesudah itu refresh token ROTASI tanpa OTP
  (`POST /auth/refresh`) — jadi script cukup login interaktif SEKALI.
- Mining: `GET /mining/status`, `POST /mining/start`, `POST /mining/claim`
  + poll `GET /mining/claim/<id>`. Slot diatur server (slotEndsAt di status).

## Jalan di VPS
```bash
python3 sible_keeper.py --login    # sekali: email + password (getpass) + OTP dari inbox
python3 sible_keeper.py --status   # cek read-only
python3 sible_keeper.py --once     # 1 putaran claim/start
# jalan terus:
nohup python3 sible_keeper.py --loop > sible.log 2>&1 &
# atau screen -S sible
```

## Pagar
- 1 akun saja (akun Bos). Token di `tokens.json` mode 600, password tidak disimpan.
- Script TIDAK memanggil boost iklan (/mining/ad) dan TIDAK mengerjakan reward-tasks.
- PERINGATAN SESI: refresh token rotasi = satu sesi aktif. Bila Bos login di
  tempat lain (app HP / browser lain), sesi script bisa mati (SESSION_CHANGED)
  dan sebaliknya. Script berhenti total bila ACCOUNT_BANNED.
- Login endpoint kena rate-limit 5x/60 dtk — jangan spam --login.
