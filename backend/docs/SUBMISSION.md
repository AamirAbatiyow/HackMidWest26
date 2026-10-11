# Submission checklist (due Sun 8:00 AM CT)

Submission method: **TBD** (likely an organizer-provided Git repo). Update this line at kickoff: ____________

## Rules that bite
- One project per team: submit **one** concept (point the README at `projects/<name>/`; mention other folders are unused scaffolds or remove them).
- Fresh code: everything here was created after kickoff (git history shows it). Third-party libraries are allowed.
- 24h hard stop: no features or bug fixes after the deadline.
- Pitch: 3 minutes, live prototype, **no slides**, already logged in, name the sponsor challenges.

## T-2h
- [ ] Concept frozen; PLAN.md cut list applied
- [ ] Deployed on Akamai; public URL works from a phone on cellular
- [ ] `make lint && make test` green; `make smoke project=<x> host=<url>` green
- [ ] Demo script rehearsed twice (docs/DEMO.md)

## T-30m
- [ ] README: what it is, which challenges, live URL, how to run, architecture link
- [ ] `projects/<x>/README.md` lists the API endpoints the frontend uses
- [ ] No secrets in git: `git grep -nIiE "(api[_-]?key|secret|private[_-]?key|seed)\s*=\s*['\"][^'\"]{8,}"` returns nothing suspicious; `.env` not tracked
- [ ] data/DATA.md lists every dataset + license; no large files committed
- [ ] Push to the submission remote (and `main` here). Note the final commit SHA: ________

## After submitting
- [ ] Don't touch the deployment except to restart it
- [ ] Keep the laptop charged, tabs open, backup recording ready
