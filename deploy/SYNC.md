# Keeping the fork current and redeploying

The workflow `.github/workflows/sync-and-deploy.yml` brings the fork's `main` up to date with `fossasia/visdom-dev` and, if you want, redeploys the test deployment. It runs every Monday at 06:00 UTC and can be started by hand from the Actions tab.

## What it does

1. Fetches `fossasia/visdom-dev` main. If the fork already has everything, it stops.
2. Merges it into a `sync/fossasia-<date>` branch with a merge commit. It is a merge and not a rebase on purpose: a rebase would rewrite the fork's history and need a force push. A squash would hide that the fork has the upstream commits.
3. If the merge has conflicts, nothing is pushed and the run fails. The conflicting files are listed in the run summary. Merge by hand.
4. Runs the whole CI workflow on the merged branch.
5. If CI is green, moves `main` forward to the merged branch (a fast-forward, never forced) and deletes the sync branch.
6. Redeploys when asked to (see below).

Nothing is ever pushed to fossasia. It is only read.

## Redeploying

A manual run has a "Redeploy the test deployment" box, on by default. A manual run redeploys even when there was nothing new to merge. The Monday run only redeploys when the repository variable `DEPLOY_ENABLED` is `true` and something was merged.

The deploy job connects to the VM over SSH and runs `git fetch origin && git merge --ff-only origin/main && docker compose build && docker compose up -d` in `DEPLOY_PATH`.

Set these in Settings, Secrets and variables, Actions:

| Name | Kind | What |
|---|---|---|
| `DEPLOY_HOST` | secret | the VM's address |
| `DEPLOY_USER` | secret | the SSH user |
| `DEPLOY_SSH_KEY` | secret | the private half of a key made only for this |
| `DEPLOY_KNOWN_HOSTS` | secret | the output of `ssh-keyscan -t ed25519 <host>` |
| `DEPLOY_PATH` | variable | the checkout on the VM, for example `~/app/visdom-dev` |
| `DEPLOY_ENABLED` | variable | `true` to redeploy on the Monday run |

Make the key on your own machine, add its public half to `~/.ssh/authorized_keys` on the VM, and paste the private half into the secret:

```bash
ssh-keygen -t ed25519 -f visdom-deploy -N "" -C "fork deploy"
ssh-copy-id -i visdom-deploy.pub <user>@<host>
ssh-keyscan -t ed25519 <host>
```

The job runs in an environment called `test-deployment`. Add required reviewers to it if you want a click before anything is deployed.

The checkout on the VM has to track the fork (`origin` is the fork) and be on `main`.

## When fossasia changes a workflow file

The built in token cannot push changes to files under `.github/workflows`. If a sync brings one in, the push fails. Add a personal access token with the `repo` and `workflow` scopes as the secret `SYNC_TOKEN` and the workflow uses it instead.
