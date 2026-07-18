# Maintainer setup

A few deliverables in this project require one-time actions in the repository's
**Settings** that a pull request cannot perform. This page lists them so they
are not forgotten.

## Enable the docs site (GitHub Pages) — #16

The [`docs.yml`](https://github.com/dgenio/intentflow/blob/main/.github/workflows/docs.yml)
workflow builds the MkDocs site and deploys it to Pages.

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. Push to `main` (or run the workflow manually) to publish.
3. Add the published URL to the repository **About** field.

## Set the social-preview image — #100

1. Generate the card (see the recording script under
   [`docs/assets/`](https://github.com/dgenio/intentflow/tree/main/docs/assets)).
2. **Settings → General → Social preview → Upload an image** (1280×640 PNG).

## Enable Discussions and seed it — #101

1. **Settings → General → Features → check "Discussions".**
2. Create categories: **Announcements** (post-only), **Q&A** (answerable),
   **Ideas**, **Show and tell**.
3. Seed the threads listed in [`community.md`](community.md) so the tab is not
   empty. The show-and-tell form template ships in
   [`.github/DISCUSSION_TEMPLATE/`](https://github.com/dgenio/intentflow/tree/main/.github/DISCUSSION_TEMPLATE).

## Publish the container image (GHCR) — #96

The `Dockerfile` builds a runnable image locally today. To publish
`ghcr.io/dgenio/intentflow` on release, add a build-and-push step to the release
workflow when it lands (tracked in #23), with `--provenance` attestation. Until
then the image is buildable but unpublished — this is intentional, not missing.

## Label colors and descriptions — #26

The label taxonomy is documented in [`labels.md`](labels.md). Colors and
descriptions are a one-time **Settings → Labels** pass.

## Turn on branch protection and required checks

Once the CI (#22) and this repo's `docs` / `security-audit` workflows are green,
mark them **required** under **Settings → Branches → Branch protection rules**.
