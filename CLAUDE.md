# ipostudio

Local-first AI desktop workstation — clean-room independent implementation.
Spec: `Functional Specification v1.0.md`. Design records: `docs/design/`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke it.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

If B: run `gstack-config set routing_declined true` — N/A (user chose A).
