# Security

Never submit API keys, ntfy tokens, authorization headers, private configuration
or unredacted personal logs in an issue. Revoke exposed keys in Immich promptly.
Use dedicated, minimally scoped user keys and HTTPS. Keep `.env` mode 0600 and secrets out of `config.yml` (use environment
references). The non-root container needs to read the bind-mounted config; mode
0644 in a host directory with mode 0700 keeps host access private. Logs and ntfy messages include album metadata.

Report security concerns privately to the repository owner when a publication
contact becomes available. Until publication, communicate findings directly to
the project owner; this repository does not invent a contact address.
