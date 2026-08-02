#!/bin/sh
# =============================================================================
# hashi Warden entrypoint — deploy/warden/entrypoint.sh
# =============================================================================
# WHAT: wires git and `gh` from the environment, then hands off to the Warden.
# WHY:  the fleet pushes branches and opens PRs as itself, so the credential has
#       to exist where the agents actually run. Doing it here, once at boot,
#       means no agent ever reads GH_TOKEN — git and gh hold it, and a token
#       that never enters a transcript never has to be rotated because of one.
# HOW:  `docker compose -f deploy/warden/docker-compose.yml up -d`. With
#       GH_TOKEN empty the project is simply local-only: the fleet reports a
#       file list instead of a PR, which is a supported mode, not a failure.
# =============================================================================
set -e

# /repo is bind-mounted from the host and owned by another uid; without this git
# refuses to touch it ("dubious ownership") and every branch command fails with
# an error that looks like a permissions bug in the fleet.
git config --global --add safe.directory /repo

if [ -n "${GIT_USER_NAME:-}" ]; then
    git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "${GIT_USER_EMAIL:-}" ]; then
    git config --global user.email "$GIT_USER_EMAIL"
fi

if [ -n "${GH_TOKEN:-}" ]; then
    git config --global credential.helper store
    printf 'https://oauth2:%s@github.com\n' "$GH_TOKEN" > "$HOME/.git-credentials"
    chmod 600 "$HOME/.git-credentials"
    # `gh` is made to hold the token in its OWN config rather than read it from
    # the environment, because warden.py now strips GH_TOKEN before handing the
    # environment to the CLI: the fleet has full Bash inside this container, and
    # a token it can `printenv` is a token in the next transcript. Without this
    # login, stripping it would leave `gh pr create` with no credential at all.
    #
    # `env -u GH_TOKEN` is required, not cosmetic: gh refuses to store a token
    # while that variable is set and exits non-zero.
    #
    # Not fatal on failure. `git push` works from the credential store above
    # regardless, so a bad token should cost the fleet its PRs and say so —
    # not kill the entrypoint and turn `restart: unless-stopped` into a loop
    # that reads as a broken image.
    if printf '%s' "$GH_TOKEN" | env -u GH_TOKEN gh auth login --with-token 2>/dev/null; then
        echo "git credentials configured for $(git config --global user.name)"
        env -u GH_TOKEN gh auth status 2>&1 | grep -i 'logged in' || true
    else
        echo "WARNING: gh auth login failed — check GH_TOKEN. git push will still"
        echo "work from the credential store; opening PRs will not."
    fi
else
    echo "GH_TOKEN is empty — local-only mode: the fleet will report changed"
    echo "files instead of opening a PR. Set it in .env to enable pushing."
fi

exec "$@"
