# ⛏️ Panduan Sible Network — Daftar + Mining Otomatis di VPS Sendiri

Mining gratis token SIBLE (proyek AI "Sible Network"). Tanpa modal, tanpa wallet.
Jujur di depan: saldo masih **off-chain** (belum bisa ditrade), token baru direncanakan
listing **2027** — anggap ini tiket gratis jangka panjang, bukan uang cepat.

## Bagian 1 — Daftar (5 menit, dari HP/laptop sendiri)

1. Buka link referral: **https://mine.sible.network/didinska**
2. Pilih **Web App** → **Daftar**
3. Isi email + buat password. Kolom **kode rujukan** isi: `didinska`
   → dapat bonus **+10 SIBLE**
4. Centang Ketentuan Layanan → **Buat Akun** → masukkan **kode OTP** dari email kamu
5. Di beranda: **Start Mining**, lalu aktifkan **AI Accelerate** (3 tingkat, total +60%)
   → rate jadi **0,16 SIBLE/jam**
6. (Opsional) Selesaikan tugas pemula di menu **Tugas** — masing-masing +1 SIBLE

## Bagian 2 — Mining otomatis di VPS kamu sendiri (opsional)

Syarat: VPS Linux + `python3` + `git`. Semua langkah dijalankan **kamu sendiri** —
password & OTP **jangan pernah dibagikan ke siapa pun**, termasuk yang mengajakmu.

```bash
git clone https://github.com/didinska21/didinska-sible-keeper.git
cd didinska-sible-keeper
python3 sible_keeper.py --login    # SEKALI: email + password + OTP kamu sendiri
                                   # (password TIDAK disimpan; yang disimpan hanya
                                   #  token di tokens.json, mode 600)
python3 sible_keeper.py --status   # cek: panel saldo & slot harus tampil
python3 sible_keeper.py --once     # 1 putaran tes claim/start
screen -S sible                    # jalan terus:
python3 sible_keeper.py --loop     #   claim + start sesi otomatis tiap slot
# keluar dari screen tanpa mematikan: Ctrl+A lalu D
# masuk lagi kapan pun: screen -r sible
```

## Aturan main (penting, jangan dilanggar)

- **1 orang = 1 akun.** Jangan buat akun kedua, jangan titip akun ke orang lain,
  jangan jalankan akun orang lain di VPS-mu. Proyek melakukan Sybil screening
  sebelum distribusi — akun yang melanggar bisa dibatalkan semua saldonya.
- Selama keeper jalan, **jangan login di HP/browser lain** — sesinya tunggal;
  login di tempat lain bisa mematikan sesi script (`SESSION_CHANGED`), dan sebaliknya.
  Cek saldo sesekali boleh, tapi sesudah itu jalankan `--login` lagi bila script error.
- File `tokens.json` = kunci akunmu. Jangan dikirim ke siapa pun.

## Kalau error

| Pesan | Artinya | Solusi |
|---|---|---|
| `TOKEN_INVALID` / `SESSION_CHANGED` terus | Sesi mati (biasanya karena login di tempat lain) | Jalankan `python3 sible_keeper.py --login` lagi |
| Login ditolak / rate limit | Endpoint login dibatasi 5×/60 detik | Tunggu 1–2 menit, coba lagi pelan-pelan |
| `MINING_SLOT_ALREADY_USED` | Slot hari ini sudah terpakai | Normal — bukan error, script lanjut sendiri |
| `ACCOUNT_BANNED` | Akun kena sanksi server | Script berhenti total. Jangan buat akun baru — hubungi yang mengajakmu |
