# Corresponding source

FreeRead is licensed under AGPL-3.0. Every M0 installer includes `source.tar.gz`
beside this file, containing the exact FreeRead source, schemas, lockfile, and
build scripts for that installer. Extract it, use the Node/pnpm versions in
`package.json`, run `pnpm install --frozen-lockfile`, `pnpm gen`, `pnpm verify`,
then `pnpm build:dist` on the target operating system.

Dependency names, versions, licenses and upstream source locations are in
`THIRD_PARTY_NOTICES.md`. Installers include no Python engines, models, fonts,
or modified third-party code. Electron upstream source is available at
https://github.com/electron/electron, with its exact version recorded in the
lockfile. The source archive is built directly from the working source so
uncommitted release changes are included. M0 packages are unsigned development
artifacts; production signing and public tag URLs belong to M7.
