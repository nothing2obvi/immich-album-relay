# Immich API compatibility and event research

Checked October 21, 2026 against a local `immich` reference checkout (server package version 3.2.0), and the official
v3.3.0 source tag. The installed local Immich and test container image labels
report v3.3.0. An authenticated live test is still required for an installation
before claiming live compatibility. Container image labels alone do not verify
that a running server responds correctly.

Target: **Immich 3.2 and 3.3**, using the supported public HTTP API. Older
versions fail validation with an actionable version message. Newer versions
need verification; incompatible response structures fail closed.

| Operation | Endpoint | API key permission |
| --- | --- | --- |
| Verify credential's immutable user ID | `GET /api/users/me` | `user.read` |
| Server version | `GET /api/server/version` | public |
| List albums / album details | `GET /api/albums`, `GET /api/albums/{id}` | `album.read` |
| Read album membership, including shared contributions | `POST /api/search/metadata` | `asset.read` |
| Add existing asset IDs | `PUT /api/albums/{id}/assets` | `albumAsset.create` |

Membership search uses the v3.2 structured filter:
`{"filter":{"albumIds":{"any":["ALBUM_UUID"]}},"size":500,"withExif":false}`
and follows `assets.nextCursor` until null. It includes archive assets under
the server's visibility policy, without searching unrelated libraries. Locked,
trashed or otherwise inaccessible assets remain subject to Immich's access rules.
There is no assumption that album-info embeds an `assets` list. v3 album-info
exposes `albumUsers`, including an `owner` role; older `ownerId` is also recognized.

Each source key needs `user.read`, `album.read`, `asset.read`,
`albumAsset.create`. A credential used solely for destination metadata validation
needs `user.read`, `album.read`. The internal `asset.share` access check in
`addAssets` checks ownership/partner relationships; it is **not an additional
API-key scope on this endpoint**. The relay deliberately restricts writes to
assets whose `ownerId` matches the authenticated source user's configured ID.
An owner key cannot substitute for another contributor's key.

Read-only validation checks identity, source/destination reads, pagination and
owner/editor role. It does not make empty PUT probes, so it cannot prove a key
has `albumAsset.create` or that every asset can be shared. Actual per-asset results
are authoritative: success, duplicate (benign), no_permission, not_found,
validation, or unknown. HTTP 400 may also mean inaccessible or missing albums;
Immich can intentionally avoid distinguishing these cases.

The reference and v3.3.0 plugin SDK's `WorkflowTrigger` exposes `AssetCreate`,
`AssetMetadataExtraction` and `AssetTagged`, with no album-membership trigger.
The presence of an outbound webhook action does not establish a reliable
“added to album” event. Internal `AlbumUpdate` events are not a supported
external webhook subscription. Therefore this release uses **membership polling**,
not upload webhooks or an unsupported socket/database interface. No listener,
webhook authentication or event recursion surface is exposed. Filtering is by
configured source UUIDs, membership fingerprints, and per-job debounce timers.
Changes caused by relaying into a source album are reconciled idempotently.

Primary references:

- [v3.3.0 album controller](https://github.com/immich-app/immich/blob/v3.3.0/server/src/controllers/album.controller.ts)
- [v3.3.0 album DTO](https://github.com/immich-app/immich/blob/v3.3.0/server/src/dtos/album.dto.ts)
- [v3.3.0 structured search DTO and cursor](https://github.com/immich-app/immich/blob/v3.3.0/server/src/dtos/search.dto.ts)
- [v3.3.0 search service album access rules](https://github.com/immich-app/immich/blob/v3.3.0/server/src/services/search.service.ts)
- [v3.3.0 album service](https://github.com/immich-app/immich/blob/v3.3.0/server/src/services/album.service.ts)
- [v3.3.0 ownership and editor access checks](https://github.com/immich-app/immich/blob/v3.3.0/server/src/utils/access.ts)
- [v3.3.0 workflow trigger types](https://github.com/immich-app/immich/blob/v3.3.0/packages/plugin-sdk/src/types.ts)
