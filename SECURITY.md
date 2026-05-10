# Security

## Secrets

Do not commit API keys, OAuth credentials, or generated tokens. This repository ignores:

- `.env`
- `credentials/*.json`
- generated media under `outputs/`

The NVIDIA API key pasted into the conversation should be treated as compromised and rotated in the NVIDIA dashboard before using this project.

## Publishing Guardrails

Uploads are disabled unless `YOUTUBE_UPLOAD_ENABLED=true` or the CLI command explicitly enables upload for that run. Keep YouTube privacy set to `private` until every video has been reviewed.

## Copyright Guardrails

The default renderer creates original animation from shapes, text, and generated motion. If you add external music, footage, images, or fonts, keep proof of license and store it with the generated package.

