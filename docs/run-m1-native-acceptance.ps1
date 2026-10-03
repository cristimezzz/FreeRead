# SPDX-License-Identifier: AGPL-3.0-only
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stageRoot = Join-Path $env:TEMP ('freeread-m1-acceptance-' + [guid]::NewGuid().ToString('N'))
$packagePath = Join-Path $repoRoot 'artifacts/win-unpacked'
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'FreeRead.exe'))) {
  throw 'Build or extract the Windows x64 package into artifacts/win-unpacked first.'
}
New-Item -ItemType Directory -Path (Join-Path $stageRoot 'artifacts') | Out-Null
Copy-Item -LiteralPath $packagePath -Destination (Join-Path $stageRoot 'artifacts') -Recurse
$sourceHash = (Get-FileHash -LiteralPath (Join-Path $packagePath 'FreeRead.exe')).Hash
$stagedHash = (Get-FileHash -LiteralPath (Join-Path $stageRoot 'artifacts/win-unpacked/FreeRead.exe')).Hash
if ($sourceHash -ne $stagedHash) { throw 'Staged executable differs from source.' }
Write-Output "Native acceptance directory: $stageRoot"
$previousPackaged = $env:FR_PACKAGED
Push-Location -LiteralPath $stageRoot
try {
  & node (Join-Path $repoRoot 'scripts/cold-start.mjs') --packaged
  $coldExitCode = $LASTEXITCODE
  $env:FR_PACKAGED = '1'
  $testConfig = Join-Path $repoRoot 'playwright.config.ts'
  $testOutput = Join-Path $repoRoot 'artifacts/m1-local-evidence'
  & node (Join-Path $repoRoot 'node_modules/@playwright/test/cli.js') test `
    "--config=$testConfig" "--output=$testOutput"
  $e2eExitCode = $LASTEXITCODE
} finally {
  Pop-Location
  $env:FR_PACKAGED = $previousPackaged
}
if ($coldExitCode -ne 0 -or $e2eExitCode -ne 0) { exit 1 }
