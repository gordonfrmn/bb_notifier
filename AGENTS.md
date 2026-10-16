# AGENTS.md

Discord notifier for new bug bounty programs / in-scope assets (H1, Bugcrowd, Intigriti, YesWeHack).

- `notifier.py`: stdlib-only. Diffs arkadiyt/bounty-targets-data against `state/seen.json` (a cumulative seen set) and posts to `DISCORD_WEBHOOK`.
- `config.json`: settings, including `mute_categories` (categories to skip; `[]` = notify everything).
- `.github/workflows/check.yml`: runs every 30 min on GitHub Actions and commits `state/` as github-actions[bot]. Never hand-edit `state/` unless you're testing.
- Local test: `DRY_RUN=1 python3 notifier.py`. `secrets.env` holds the webhook locally.
- `secrets.env` and `deploy_keys/` are gitignored. Never commit them.

## Committing
- Commit only as the repo owner's account: `gordonfrmn <gordonfrmn@users.noreply.github.com>`. No personal emails, and no `Co-Authored-By` or other AI attribution trailers.
- Push only with the deploy key, to `git@github.com:gordonfrmn/bb_notifier.git`. The key in `deploy_keys/` has loose permissions under /mnt/c, so copy it to a temp file with `chmod 600` and set `GIT_SSH_COMMAND="ssh -i <copy> -o IdentitiesOnly=yes"`.
- Run `git pull --rebase` before pushing, because the bot commits state.
