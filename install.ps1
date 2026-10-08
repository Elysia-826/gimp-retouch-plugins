# gimp-retouch-plugins installer for Windows -- tested on Windows 11 + GIMP 3.2.6 (headless, 2026-10-08); GUI dialogs 尚未人工验证
# Installs OUR plugins (fsep_oneclick, dnb_setup, batch_export) into %APPDATA%\GIMP\<ver>\plug-ins.
# Third-party plugins: prints the pinned manual steps from bundle.lock (no automatic install on Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1 [-Gimp 3.0|3.2|all] [-Only ours|third-party|all] [-BackupDir D:\gimp-bundle-backups] [-Reinstall] [-DryRun]
# -Gimp all = every version that already has a profile in %APPDATA%\GIMP; a fresh GIMP (never started) needs -Gimp 3.2 explicitly.
param(
  [ValidateSet("3.0","3.2","all")][string]$Gimp = "all",
  [ValidateSet("ours","third-party","all")][string]$Only = "all",
  [string]$BackupDir = (Join-Path $env:USERPROFILE "gimp-bundle-backups"),
  [switch]$Reinstall, [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vers = if ($Gimp -eq "all") { @("3.0","3.2") | Where-Object { Test-Path (Join-Path $env:APPDATA "GIMP\$_") } } else { @($Gimp) }
if ($Only -ne "third-party" -and -not $Vers) { [Console]::Error.WriteLine("No GIMP 3.x profile found in $env:APPDATA\GIMP. Start GIMP once, or pass -Gimp 3.0 / -Gimp 3.2."); exit 64 }
$Ours = @{ "fsep_oneclick" = @("fsep_oneclick\fsep_oneclick.py");
           "dnb_setup"     = @("dnb_setup\dnb_setup.py");
           "batch_export"  = @("batch_export\batch_export.py","batch_export\cli_run.py") }
$Procs = @{ "fsep_oneclick"="python-fu-fsep-oneclick"; "dnb_setup"="python-fu-dnb-setup"; "batch_export"="python-fu-batch-export" }
function Do-It($desc, [scriptblock]$sb) { if ($DryRun) { Write-Host "    [dry-run] $desc" } else { Write-Host "    + $desc"; & $sb } }
function Sha($p) { if (Test-Path $p) { (Get-FileHash -Algorithm SHA256 $p).Hash } else { "" } }

if (Get-Process -Name "gimp*" -ErrorAction SilentlyContinue) { Write-Warning "GIMP is running; restart it afterwards (not killing it)." }
$rows = @()
foreach ($v in $Vers) {
  $prof = Join-Path $env:APPDATA "GIMP\$v"
  $pd = Join-Path $prof "plug-ins"
  if (Test-Path $prof) {
    $bk = Join-Path $BackupDir ("gimp-config-$v-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")
    Do-It "backup $prof -> $bk" { New-Item -ItemType Directory -Force (Split-Path $bk) | Out-Null; Compress-Archive -Path "$prof\*" -DestinationPath $bk }
  }
  if ($Only -ne "third-party") {
    foreach ($id in $Ours.Keys) {
      $dst = Join-Path $pd $id; $need = [bool]$Reinstall
      foreach ($f in $Ours[$id]) { if ((Sha (Join-Path $Repo $f)) -ne (Sha (Join-Path $dst (Split-Path $f -Leaf)))) { $need = $true } }
      if ($need) {
        Do-It "install $id -> $dst" { New-Item -ItemType Directory -Force $dst | Out-Null
          foreach ($f in $Ours[$id]) { Copy-Item -Force (Join-Path $Repo $f) $dst } }
        $act = if ($DryRun) { "would-install" } else { "installed" }
      } else { $act = "ok (up to date)" }
      $rc = Join-Path $prof "pluginrc"
      $reg = if ((Test-Path $rc) -and (Select-String -Quiet -SimpleMatch "(proc-def `"$($Procs[$id])`"" $rc)) { "yes" } else { "not yet (start GIMP once)" }
      $rows += [pscustomobject]@{ GIMP=$v; Component=$id; Action=$act; Registered=$reg }
    }
  }
}
$rows | Format-Table -AutoSize
if ($Only -ne "ours") {
  Write-Host "`nThird-party (manual on Windows, pinned versions from bundle.lock):"
  Get-Content (Join-Path $Repo "bundle.lock") | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() } | ForEach-Object {
    $c = $_.Split('|') | ForEach-Object { $_.Trim() }
    if ($c[3] -ne "ours") { Write-Host ("  - {0} {1} [{2}] {3}  sha256/commit={4}" -f $c[0],$c[2],$c[1],$c[4],$c[5]) }
  }
  Write-Host @"
  Windows notes:
   * G'MIC-Qt: use the official Windows installer for GIMP 3 from https://gmic.eu/download.html (version 4.0.5).
   * Resynthesizer: Windows builds from https://github.com/bootchk/resynthesizer/releases (v3.0 for GIMP 3.0, v3.0.1 for 3.2).
   * Batcher 1.2.10: unzip batcher-1.2.10.zip and copy the 'batcher' folder into %APPDATA%\GIMP\<ver>\plug-ins\.
   * adjustment-layer: copy adjustment-layer.py (commit cc07757) to %APPDATA%\GIMP\<ver>\plug-ins\adjustment-layer\.
   * Verify each download's SHA256 with: Get-FileHash -Algorithm SHA256 <file>
"@
}
