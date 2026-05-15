Clause-CLM — Setup Guide
> This guide covers everything needed to get Clause-CLM running from scratch on a fresh Ubuntu / WSL2 environment.
---
Prerequisites
Ubuntu 24.04 (native or WSL2 on Windows)
`sudo` access
Internet connection
Git (to clone the repo)
---
Step 1 — Clone the Repository
```bash
cd ~
git clone <your-repo-url> Clause-CLM
cd Clause-CLM
```
> **WSL2 note:** Always work inside the Linux filesystem (`/home/<user>/...`), not on a Windows path (`/mnt/c/...`). Working from a Windows path causes `EPERM` errors during `npm install`.
---
Step 2 — Fix File Ownership (WSL2 only)
If you copied the project from Windows into WSL, files may be owned by `root`. Fix this first:
```bash
sudo chown -R $USER:$USER ~/Clause-CLM
```
---
Step 3 — Install Docker
```bash
# Install dependencies
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker's APT repository (using .sources format — avoids the invalid filename warning)
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Verify Docker is running
sudo systemctl status docker
```
> **Why `.sources` instead of `.list`?** The old command using `| sudo tee docker.list > /dev/null` with a space creates a file named `docker. List` (capital L, space before extension) which is invalid and gets ignored. The `.sources` format avoids this entirely.
Optional — run Docker without sudo
```bash
sudo usermod -aG docker $USER
# Then log out and back in, or run: newgrp docker
```
---
Step 4 — Install Node.js (WSL2 only)
The Windows Node.js install doesn't work inside WSL. Install the Linux version:
```bash
sudo apt install -y nodejs npm
# Verify
node --version   # should be v18+ or v22+
npm --version
```
---
Step 5 — Create the `.env` File
Create `.env` in the project root (`~/Clause-CLM/.env`):
```env
# ── Database ───────────────────────────────────────────────────────────
DATABASE_NAME=Clause

# ── Clerk Authentication ───────────────────────────────────────────────
VITE_CLERK_PUBLISHABLE_KEY=<your_clerk_publishable_key>
CLERK_SECRET_KEY=<your_clerk_secret_key>
CLERK_ISSUER=<your_clerk_issuer_url>

# ── Frontend ───────────────────────────────────────────────────────────
VITE_API_BASE_URL=https://localhost/api

# ── Backend ────────────────────────────────────────────────────────────
SECRET_KEY=<a_random_secret_key>
GOOGLE_CLIENT_ID=<your_google_client_id>
GOOGLE_CLIENT_SECRET=<your_google_client_secret>
GOOGLE_REDIRECT_URI=https://localhost/api/calendar/callback

# ── SMTP Email ─────────────────────────────────────────────────────────
SMTP_EMAIL=<your_gmail_address>
SMTP_PASSWORD=<your_gmail_app_password>

# ── Elasticsearch ──────────────────────────────────────────────────────
ELASTIC_PASSWORD=changeme_in_production
INDEX_NAME=clm_knowledge_base

# ── AI Agents — Gemini ─────────────────────────────────────────────────
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MODEL_LITE=gemini-2.5-flash
GEMINI_MODEL_HEAVY=gemini-2.5-flash
GEMINI_RPM=15
GEMINI_RPD=500
GEMINI_MODEL_LIMITS=gemini-2.5-pro:0:0,gemini-2.5-flash:5:20

# ── AI Agents — Anthropic ──────────────────────────────────────────────
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_ENABLED=true

# ── AI Agents — Ollama (local model) ──────────────────────────────────
OLLAMA_MODEL=qwen2.5:7b-instruct
LOCAL_MODEL_ENABLED=false        # set true only if you have a GPU + Ollama set up

# ── CORS ───────────────────────────────────────────────────────────────
CORS_ORIGINS=https://localhost,http://localhost
```
Variable	Notes
`VITE_CLERK_PUBLISHABLE_KEY`	Required — get from clerk.com dashboard
`CLERK_SECRET_KEY`	Required for production; can be left blank for local dev
`GOOGLE_CLIENT_ID/SECRET`	Only needed for Google Calendar integration
`ELASTIC_PASSWORD`	Must match exactly in both `.env` and the secrets file below
`LOCAL_MODEL_ENABLED`	Set `false` unless you have a GPU — removes the NVIDIA requirement
---
Step 6 — Create Secrets Files
These are read by Docker services at runtime:
```bash
mkdir -p ~/Clause-CLM/ingestion/secrets

echo "<your_gemini_api_key>"     > ~/Clause-CLM/ingestion/secrets/gemini_api_key.txt
echo "changeme_in_production"    > ~/Clause-CLM/ingestion/secrets/elastic_password.txt
echo "<your_anthropic_api_key>"  > ~/Clause-CLM/ingestion/secrets/anthropic_api_key.txt
```
> The value in `elastic_password.txt` must be identical to `ELASTIC_PASSWORD` in your `.env`.
---
Step 7 — Create the Frontend Environment File
Vite reads env vars from `frontend/.env.local`, not the root `.env`:
```bash
cat > ~/Clause-CLM/frontend/.env.local <<EOF
VITE_CLERK_PUBLISHABLE_KEY=<your_clerk_publishable_key>
VITE_API_BASE_URL=https://localhost/api
EOF
```
---
Step 8 — Build the Frontend
```bash
cd ~/Clause-CLM/frontend
npm install
npm run build
```
The compiled output lands in `frontend/dist/`, which the nginx Docker image picks up.
---
Step 9 — Build & Start with Docker Compose
```bash
cd ~/Clause-CLM
sudo docker compose up -d --build
```
Check that all services came up:
```bash
sudo docker compose ps
```
Expected output — all services should show `Up` or `Up (healthy)`:
Service	Container	Port
nginx	clm_nginx	80, 443
backend	clm_backend	(internal)
agents	clm_agents	(internal)
worker	clm_worker	(internal)
elasticsearch	elasticsearch	(internal)
mongo	mongo	(internal)
redis	redis_cache	(internal)
ollama	ollama	(internal)
Open https://localhost in your browser. Accept the self-signed certificate warning.
---
Step 10 — Make a User an Admin (optional)
If you need to grant admin access to an account after first login:
```bash
sudo docker exec mongo mongosh --quiet Clause --eval '
  db.users.updateOne(
    { email: "your@email.com" },
    { $set: { role: "admin" } }
  )
'
```
Then log out and back in on the app for the role change to take effect.
---
Troubleshooting
White screen after opening the app
Vite bakes environment variables at build time. If the frontend was built before `frontend/.env.local` existed, the Clerk key will be empty and the app will crash silently. Fix:
```bash
cd ~/Clause-CLM/frontend
# Make sure frontend/.env.local exists with your Clerk key, then:
npm run build
cd ~/Clause-CLM
sudo docker compose build nginx
sudo docker compose up -d nginx
```
Then hard-refresh in the browser with `Ctrl+Shift+R`.
---
Docker permission denied
```
permission denied while trying to connect to the Docker daemon socket
```
Either prefix commands with `sudo`, or add yourself to the docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```
---
`docker. List` — invalid filename warning
```
Notice: Ignoring file 'docker.' in directory '/etc/apt/sources.list.d/' as it has an invalid filename extension
```
This was caused by a typo in the `tee` command that created a file with a space in the name. Remove it and use the `.sources` method from Step 3:
```bash
sudo rm /etc/apt/sources.list.d/docker.*
# Then redo Step 3
```
---
`unable to prepare context: path ... not found`
The `docker-compose.yml` had incorrect build context paths (`../cluasue`, `../cluasue/Backend`). These should be:
nginx context: `.` (project root)
backend context: `./backend`
Also check `nginx/Dockerfile` — the static files copy should be:
```dockerfile
COPY frontend/dist /var/www/clause
```
---
NVIDIA GPU error on startup (no GPU machine)
```
Error response from daemon: could not select device driver "nvidia"
```
In `docker-compose.yml`, find the `ollama` service and remove the `deploy.resources.reservations.devices` block entirely. This is safe when `LOCAL_MODEL_ENABLED=false`.
---
npm install fails with EPERM
You're running npm from the Windows Node.js installation, or `node_modules` is owned by root. Fix:
```bash
# Install Linux Node.js
sudo apt install -y nodejs npm

# Fix ownership if needed
sudo chown -R $USER:$USER ~/Clause-CLM/frontend/node_modules

# Then use the Linux npm explicitly
/usr/bin/npm install
```
---
Stopping the App
```bash
cd ~/Clause-CLM
sudo docker compose down
```
To also remove volumes (wipes database data):
```bash
sudo docker compose down -v
```
