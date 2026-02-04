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
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && git pull origin main && chmod +x run.sh"
sprite exec -s linksite-dev -- bash -c "sprite-env services stop linksite; sleep 2; sprite-env services start linksite"
```

## One-liner Deploy

```bash
# After pushing locally:
sprite exec -s linksite-dev -- bash -c "cd /home/sprite/linksite && git pull origin main && chmod +x run.sh && sprite-env services stop linksite; sleep 2; sprite-env services start linksite"
```

## URLs

- **Live app:** https://linksite-dev-bawuw.sprites.app/
- **GitHub repo:** https://github.com/sdwr/linksite

## Service Setup

The app runs as a Sprite service, which means it:
- Persists between reboots
- Auto-starts when HTTP requests hit the URL
- Uses the proper service manager

### First-time setup:
```bash
# Create run.sh wrapper and service
sprite exec -s linksite-dev -- bash -c "chmod +x /home/sprite/linksite/run.sh"
sprite exec -s linksite-dev -- sprite-env services create linksite --cmd /home/sprite/linksite/run.sh --http-port 8080
```

### Service management:
```bash
# List services
sprite exec -s linksite-dev -- sprite-env services list

# Restart (use stop/start, not restart - restart command is broken)
sprite exec -s linksite-dev -- bash -c "sprite-env services stop linksite; sleep 2; sprite-env services start linksite"

# Stop/Start individually
sprite exec -s linksite-dev -- sprite-env services stop linksite
sprite exec -s linksite-dev -- sprite-env services start linksite
```

### View logs:
```bash
sprite exec -s linksite-dev -- cat /.sprite/logs/services/linksite.log
sprite exec -s linksite-dev -- tail -f /.sprite/logs/services/linksite.log
```

## Troubleshooting

### Site down after deploy
1. Git pull resets `run.sh` permissions (Windows doesn't preserve +x bit)
2. Always run `chmod +x run.sh` after pulling
3. Use stop + sleep + start, not restart

### Service shows "running" but site is down
```bash
# Check if process is actually running
sprite exec -s linksite-dev -- bash -c "ps aux | grep python"

# If no python process, recreate service:
sprite exec -s linksite-dev -- bash -c "sprite-env services delete linksite"
sprite exec -s linksite-dev -- bash -c "chmod +x /home/sprite/linksite/run.sh && sprite-env services create linksite --cmd /home/sprite/linksite/run.sh --http-port 8080"
```

## Notes

- Both local and sprite remotes have PAT auth baked into the URL
- No interactive prompts needed for push/pull
- `run.sh` loads `.env` and runs the app
- Old `start.sh`/`stop.sh` scripts are deprecated - use sprite-env services instead
- App takes ~5-8 seconds to fully start up after service starts
