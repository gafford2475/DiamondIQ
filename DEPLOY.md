# Running DiamondIQ

There are two ways to run it:

1. **Hosted (recommended)** — one web address that works on your phone, your laptop and your staff's devices, anywhere.
2. **On your own laptop** — free, and works without internet once running. A phone can reach it only on the same Wi-Fi.

Both give the same app. On a laptop browser you get a sidebar layout and keyboard shortcuts for charting. On a phone you get the touch layout.

---

## Option 1: Host it on Render

Render runs the app, gives it an `https://` address, and redeploys automatically whenever this GitHub repo changes. The repo includes `render.yaml`, which describes everything Render needs.

**Cost:** a paid instance is required because the database and videos need a persistent disk. That's the Starter plan plus about 10 GB of disk; check render.com/pricing for current prices. You can resize the disk later.

1. Sign up at **render.com** with your GitHub account.
   - If GitHub asks, give Render access to the `DiamondIQ` repository.
2. In Render, click **New → Blueprint**, pick the `DiamondIQ` repository, and click **Apply**.
3. Optional: when it asks for `DIAMONDIQ_ADMIN_EMAIL` and `DIAMONDIQ_ADMIN_PASSWORD`, you can enter your admin email and a password of 10+ characters. Your admin account is then created automatically. If you leave them blank, use the setup code in step 5.
4. Wait for the first deploy to finish. It takes several minutes, because it installs the video-analysis engine.
5. Open the service, go to **Logs**, and find the line `DiamondIQ setup: ... use setup code XXXX-XXXX-XXXX`.
6. Open the service's address (`https://diamondiq-….onrender.com`). Enter the setup code, your name, email and password. You're now the admin.
7. Add your staff under **Account → Add user**:
   - **Scouts** can add and edit everything.
   - **Viewers** can only look.
   - **Admins** can also manage users.

   Give each person their temporary password privately; they can change it under Account.

**On your phone:** open the address in Safari (iPhone) or Chrome (Android). Use **Share → Add to Home Screen** (iPhone) or **⋮ → Install app** (Android). It then opens full-screen like an app, and the charting screen keeps working with no signal.

**On your laptop:** open the same address in any browser. You may want to bookmark it.

**Your own domain (optional):** in Render, open **Settings → Custom Domains** and follow the DNS steps.

**Backups:** Render takes daily snapshots of the disk. You can also download a copy from the service's **Shell** tab (`/data/diamondiq.db` is the whole database).

**Locked out?** In Render's **Shell** tab run:

```
python -m diamondiq.manage reset-password --email you@example.com
```

---

## Option 2: Run it on your laptop

### With Docker (Mac, Windows, Linux)

1. Install **Docker Desktop** from docker.com and start it.
2. Download this repository. Either use GitHub's **Code → Download ZIP** and unzip it, or run `git clone https://github.com/gafford2475/DiamondIQ.git`.
3. Open a terminal in that folder and run:

   ```
   docker compose up --build
   ```

   The first build takes several minutes.
4. Open **http://localhost:8000**. Enter the setup code printed in the terminal to create your admin account.

Stop it with `Ctrl+C`; start it again later with `docker compose up`. Your data is kept in a Docker volume between runs.

**Using your phone with the laptop:**
1. Keep both on the same Wi-Fi.
2. Find the laptop's IP address:
   - **Mac:** System Settings → Wi-Fi → Details.
   - **Windows:** run `ipconfig`.
3. On the phone, open `http://<that-IP>:8000`.

Over plain `http` on a home network, the phone can't install the app or cache it for offline use; that needs the hosted `https` version. Charting still works while connected.

### Without Docker (Python 3.11+)

```
pip install -e ".[video]"
python -m diamondiq.biomechanics.pose --download
uvicorn diamondiq.api.main:app --host 0.0.0.0 --port 8000
```

On Linux servers, MediaPipe also needs `libegl1 libgles2 libgl1` from apt.

---

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` / `DIAMONDIQ_DATABASE_URL` | SQLite file in the working directory (`/data` in Docker) | Any SQLAlchemy URL. A host's `postgres://` URL works as-is. |
| `DIAMONDIQ_SECURE_COOKIES` | `0` | Set to `1` whenever the site is served over HTTPS (the Render blueprint does this). |
| `DIAMONDIQ_ADMIN_EMAIL` / `DIAMONDIQ_ADMIN_PASSWORD` | unset | Create the first admin automatically instead of using the setup code. |
| `DIAMONDIQ_SESSION_DAYS` | `30` | How long a sign-in lasts. |
| `DIAMONDIQ_MEDIA_DIR` | `./media` | Where uploaded videos are stored. |

**Moving to Postgres:** for a bigger staff, create a Postgres database (Render, Neon, Supabase, etc.) and set `DATABASE_URL`. Tables are created automatically on startup. Data already in SQLite is not copied over.

## Security notes

- Every data endpoint requires sign-in. Passwords are hashed with scrypt, and sessions use HttpOnly cookies (only a hash of each session token is stored).
- Repeated wrong passwords are throttled. Disabling a user or resetting their password signs them out everywhere.
- The first admin can only be created with the setup code from the server log, so a new deployment can't be claimed by a stranger.
- Scripts can call the API with `Authorization: Bearer <token>` using the `token` returned by `POST /auth/login`.
