# Linksite Deployment Workflow

## Quick Deploy (from local)

```bash
# 1. Make changes locally
cd C:\Users\roryk\clawd\linksite

# 2. Commit and push
git add .
git commit -m "your message"
git push origin main

# 3. Pull on sprite and restart service
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && git pull origin main"
sprite exec -s linksite-dev -- sprite-env services restart linksite
```

## One-liner Deploy

```bash
# After pushing locally:
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && git pull origin main && sprite-env services restart linksite"
```

## URLs

- **Live app:** https://linksite-dev-bawuw.sprites.app/
- **GitHub repo:** https://github.com/sdwr/linksite

## Service Setup

The app runs as a Sprite service, which means it:
- Persists between reboots
- Auto-starts when HTTP requests hit the URL
- Uses the proper service manager

### First-time setup (already done):
```bash
# Create run.sh wrapper and service
sprite exec -s linksite-dev -- sprite-env services create linksite --cmd /home/sprite/linksite/run.sh --http-port 8080
```

### Service management:
```bash
sprite exec -s linksite-dev -- sprite-env services list
sprite exec -s linksite-dev -- sprite-env services restart linksite
sprite exec -s linksite-dev -- sprite-env services stop linksite
sprite exec -s linksite-dev -- sprite-env services start linksite
```

### View logs:
```bash
sprite exec -s linksite-dev -- cat /.sprite/logs/services/linksite.log
```

## Notes

- Both local and sprite remotes have PAT auth baked into the URL
- No interactive prompts needed for push/pull
- `run.sh` loads `.env` and runs the app
- Old `start.sh`/`stop.sh` scripts are deprecated - use sprite-env services instead
