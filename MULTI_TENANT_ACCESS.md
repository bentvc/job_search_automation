# Multi-Tenant Access — Share Your Instance with a Friend

You can run the app on **your machine** and give a non-technical friend access via the browser. They use **My Shortlist** as their tenant; you keep **Cockpit** and full pipeline.

---

## 1. One-time setup

```bash
# Create tenants + backfill job–tenant data
python migrate_multitenant.py
```

This creates **Bent** and **Friend**, and copies existing scored/shortlisted jobs into `job_tenant` for both. After each scrape+score, run **Sync jobs to tenants** in the UI (or `python sync_job_tenant.py`) so new jobs appear in **My Shortlist** for both.

---

## 2. Run Streamlit so others can reach it

```bash
streamlit run ui_streamlit.py --server.port 8501 --server.address 0.0.0.0
```

- **Same WiFi (e.g. home):** Friend opens `http://<your-lan-ip>:8501` (e.g. `http://192.168.1.10:8501`). Find your IP: `hostname -I` (Linux) or `ipconfig` (Windows).
- **Over the internet:** Use a tunnel so you don’t open your home network.

### Option A: ngrok

```bash
ngrok http 8501
```

Use the HTTPS URL ngrok prints (e.g. `https://abc123.ngrok.io`). Share that with your friend. Restart ngrok when you restart Streamlit if the URL changes (free tier).

### Option B: Cloudflare Tunnel (cloudflared)

```bash
cloudflared tunnel --url http://localhost:8501
```

Use the `*.trycloudflare.com` URL it gives you.

---

## 3. What your friend does

1. Open the URL you shared.
2. In the sidebar, **Viewing as** → choose **Friend**.
3. Open the **📋 My Shortlist** tab.
4. Browse scored/shortlisted jobs and use **Apply / View posting** links.

They never touch **Cockpit**, scrape, or sync. They only use **My Shortlist**.

---

## 4. Security note

- The UI has **no login**. Anyone with the URL can open it. Use ngrok/cloudflared only with people you trust, and avoid sharing the link widely.
- For a more locked-down setup later, you could put Streamlit behind a reverse proxy with basic auth or OIDC.

---

## 5. Optional: same shortlist for both (current behavior)

Right now, **Bent** and **Friend** see the **same** shortlist (same jobs, same scores). Scoring uses your profile; we just split the **view** by tenant. To give your friend **their own** shortlist later, you’d add per-tenant profiles and score jobs separately per tenant (see `Tenant.profile_summary` and scoring changes).
