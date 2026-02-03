# Linksite Deployment Workflow

## Quick Deploy (from local)

```bash
# 1. Make changes locally
cd C:\Users\roryk\clawd\linksite

# 2. Commit and push
git add .
git commit -m "your message"
git push origin main

# 3. Pull on sprite
sprite exec -s linksite-dev -- git -C /home/sprite/linksite pull origin main

# 4. Restart app
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && ./stop.sh && ./start.sh"
```

## One-liner Deploy

```bash
# After pushing locally:
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && git pull origin main && ./stop.sh && ./start.sh"
```

## URLs

- **Live app:** https://linksite-dev-bawuw.sprites.app/
- **GitHub repo:** https://github.com/sdwr/linksite

## Notes

- Both local and sprite remotes have PAT auth baked into the URL
- No interactive prompts needed for push/pull
- `start.sh` runs backend (port 8000) and frontend (port 8080)
- Frontend proxies to backend via Next.js rewrites
