# Deploying SYNTHESIS for ₹0 / $0

Everything in this repository is free and open-source. No API keys, no paid
LLM calls, no subscriptions. The data sources (USGS, Open-Meteo) are free
public feeds. Here is every zero-cost way to run and share it.

---

## 1. Your own PC (completely free, works offline)

```bash
git clone https://github.com/authorsauravkushwaha/SYNTHESIS
cd SYNTHESIS
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` → click **⬇ Install app** → SYNTHESIS becomes a
desktop app. Phones on the same Wi-Fi can open `http://<your-pc-ip>:8000` and
*Add to Home Screen* — a free "mobile app" for your whole team.

## 2. Hugging Face Spaces (free forever tier, public URL, Docker)

1. Create a free account at huggingface.co → New Space → **Docker** template.
2. Push this repo to the Space (it already has the `Dockerfile`):

```bash
git remote add hf https://huggingface.co/spaces/<you>/synthesis
git push hf main
```

3. In the Space settings set the port to `8000`. Done — a permanent free
   public URL, installable as a PWA from any phone.

## 3. Render.com (free web service tier)

- New → Web Service → connect the GitHub repo.
- Runtime: Docker (auto-detected). Instance type: **Free**.
- Note: free instances sleep after inactivity and wake on request — fine for
  demos and hackathon judging.

## 4. Fly.io / Railway / Google Cloud Run

All have free allowances that comfortably run this single small container:

```bash
# Fly.io example
fly launch --no-deploy      # detects Dockerfile
fly deploy
```

Cloud Run: `gcloud run deploy synthesis --source . --allow-unauthenticated`
(free tier: 2M requests/month).

## 5. GitHub Codespaces (free monthly hours)

Open the repo → Code → Codespaces → create. Run the uvicorn command; Codespaces
gives you a free forwarded public URL instantly. Zero setup.

## 6. A phone as the server (yes, really)

Termux on Android (free, no root):

```bash
pkg install python git clang
git clone https://github.com/authorsauravkushwaha/SYNTHESIS && cd SYNTHESIS
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Your phone now serves the causal world model to every device on the network.

---

## What stays free as you scale

| Need | Free option |
|---|---|
| CI/CD | GitHub Actions (already configured, free for public repos) |
| Container registry | GitHub Container Registry (free for public images) |
| Postgres + PostGIS | Neon / Supabase free tiers, or the docker-compose service |
| Redis | Upstash free tier, or the docker-compose service |
| Object storage | Cloudflare R2 free tier (10 GB) |
| Monitoring | UptimeRobot free tier + `/healthz` |
| Artifact signing | Sigstore cosign — free and keyless by design |
| Live data | USGS, Open-Meteo, NOAA, GDACS — all free public feeds |
| TLS | Let's Encrypt / automatic on all hosts above |

The vision's security posture (§22) was deliberately chosen to be implementable
with free, open tooling: SBOM via `syft`, scanning via `trivy` and `pip-audit`,
signing via `cosign`, provenance via SLSA GitHub generators — all free.
