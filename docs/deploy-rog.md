# Deploying to the ROG

There is no CD. Production is the ROG (`inmo-demo.ekoaiautomation.com`, backend
`:8011`, frontend `:3004`), and a release is four manual steps.

## Normal path (the repo is pushed)

```bash
ssh pcrug-ts
cd ~/Eko-AI-RealEstate
git pull
docker compose exec eko-realestate-backend alembic upgrade head
docker compose build eko-realestate-frontend
docker compose up -d eko-realestate-backend eko-realestate-frontend
```

## When the push is blocked

Commits can be moved without GitHub, and this is preferable to copying files
around: a bundle carries the real commits and tags, so when the push does
happen the ROG's history already matches and nothing has to be reconciled.

```bash
# on the Mac — everything the ROG does not have yet
git bundle create /tmp/eko-deploy.bundle <rog-HEAD>..main --tags
scp /tmp/eko-deploy.bundle pcrug-ts:/tmp/

# on the ROG
cd ~/Eko-AI-RealEstate
git bundle verify /tmp/eko-deploy.bundle   # must list its prerequisite as present
git fetch /tmp/eko-deploy.bundle 'refs/heads/main:refs/remotes/bundle/main' 'refs/tags/*:refs/tags/*'
git merge --ff-only refs/remotes/bundle/main
```

`git bundle verify` failing means the ROG does not have the commit the bundle
was built from. Rebuild it from whatever `git log -1` says there.

## Frontend rebuilds are not optional

Every `NEXT_PUBLIC_*` is inlined **at build time**. Restarting the container
picks up nothing — the landing content, the Turnstile site key and the capture
form key all need `docker compose build eko-realestate-frontend`.

The build also downloads Instrument Serif and Instrument Sans through
`next/font`, so it needs network access. It self-hosts them into the image, so
nothing is fetched at run time.

## Before you build: disk

The ROG runs four stacks. Check first — a build that fills the disk takes the
other three down with it:

```bash
df -h /
docker system df
```

At the last check: 90% used, 98 GB free, with ~97 GB reclaimable in images and
~56 GB in build cache. There is room, but it is worth a `docker builder prune`
**only** after confirming with whoever owns the other stacks.

## Verify, and not with a 200

```bash
curl -s https://inmo-demo.ekoaiautomation.com/api/v1/health | jq '{version, captcha}'
```

`version` must be the one you just shipped, and `captcha` says whether Turnstile
is actually verifying — `"off"` means the form has no bot protection however
correct the site key looks.

Then open it in a browser, on a phone width, in both languages, and use the
thing you changed. This install has twice shipped a route that answered 200
while the page behind it was broken.

## Rolling back

The migrations are reversible; `alembic downgrade -1` and rebuild the previous
image. Read the migration first — **029 deletes call-anchored follow-ups on the
way down**, deliberately, because leaving them would produce rows nothing can
ever cancel.
