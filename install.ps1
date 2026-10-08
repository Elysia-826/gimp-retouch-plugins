# gimp-retouch-plugins installer for Windows -- tested on Windows 11 + GIMP 3.2.6 (headless, 2026-10-08); GUI dialogs 尚未人工验证
# Installs the components YOU choose into %APPDATA%\GIMP\<ver>\ (user profile only, no admin needed):
#   ours:        fsep_oneclick, dnb_setup, batch_export, mesh_liquify (files from this repo)
#   third-party: gmic, resynthesizer, batcher, adjustment-layer    (downloaded, sha256-checked)
#   opt-in:      photogimp  (overwrites layout/shortcuts/tool presets; keeps your language/theme/icon gimprc settings)
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -List
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Components fsep_oneclick,gmic,batcher [-Gimp 3.2] [-BackupDir D:\gimp-bundle-backups]
#              [-CacheDir D:\Downloads\gimp-bundle-cache] [-Reinstall] [-DryRun]
#   -Only ours|third-party|all  = shortcut for a component set (photogimp is never included implicitly; name it in -Components).
#   -Gimp all = every version that already has a profile in %APPDATA%\GIMP; a fresh GIMP (never started) needs -Gimp 3.2 explicitly.
#   -CacheDir: downloads are kept/reused there; a file already present with the right sha256 is not downloaded again
#              (useful when GitHub is slow: put the files there yourself).
param(
  [ValidateSet("3.0","3.2","all")][string]$Gimp = "all",
  [ValidateSet("","ours","third-party","all")][string]$Only = "",
  [string[]]$Components = @(),
  [string]$BackupDir = (Join-Path $env:USERPROFILE "gimp-bundle-backups"),
  [string]$CacheDir = (Join-Path $env:TEMP "gimp-bundle-cache"),
  [switch]$Reinstall, [switch]$DryRun, [switch]$List
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Utf8 = New-Object System.Text.UTF8Encoding $false
$PreserveKeys = "language,theme,icon-theme,prefer-dark-theme,theme-color-scheme,font-relative-size,override-theme-icon-size,custom-icon-size,icon-size,import-raw-plug-in".Split(",")

# id -> definition. kind: ours | zip (copy top-level dirs) | rawfile | config (profile overlay from a tarball)
$C = [ordered]@{
  "fsep_oneclick"   = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("fsep_oneclick\fsep_oneclick.py"); procs=@("python-fu-fsep-oneclick") }
  "dnb_setup"       = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("dnb_setup\dnb_setup.py"); procs=@("python-fu-dnb-setup") }
  "batch_export"    = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("batch_export\batch_export.py","batch_export\cli_run.py"); procs=@("python-fu-batch-export") }
  "mesh_liquify"    = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("mesh_liquify\mesh_liquify.py","mesh_liquify\face_detect.py","mesh_liquify\face_detection_yunet_2023mar.onnx"); procs=@("python-fu-mesh-liquify","python-fu-mesh-liquify-stroke-layer","python-fu-mesh-liquify-undo","python-fu-mesh-liquify-redo","python-fu-mesh-liquify-face") }
  "spot_heal"       = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("spot_heal\spot_heal.py"); procs=@("python-fu-spot-heal") }
  "dnb_flow"        = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("dnb_flow\dnb_flow.py"); procs=@("python-fu-dnb-flow") }
  "subject_mask"    = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("subject_mask\subject_mask.py","subject_mask\subject_select.py"); procs=@("python-fu-subject-select") }
  "gmic"            = @{ kind="zip"; gimp="3.2"; ver="4.0.5"; file="gmic_4.0.5_gimp3.2_win64.zip"
                         url="https://gmic.eu/files/windows/gmic_4.0.5_gimp3.2_win64.zip"
                         sha="739bc467de3f6e61f85d827f5444339268145f4b3aaddbdb834b1e3b2ce7a950"; dirs=@("gmic_gimp_qt"); procs=@("plug-in-gmic-qt")
                         note="official gmic.eu GIMP 3.2 build (gmic.eu publishes no checksum; sha pinned by us 2026-10-08)" }
  "resynthesizer"   = @{ kind="zip"; gimp="3.2"; ver="3.0.1"; file="resynthesizer-3.0.1-gimp3-win64.zip"
                         url="https://github.com/ravik453/resynthesizer-windows-build/releases/download/v3.0.1-gimp3-windows/resynthesizer-3.0.1-gimp3-win64.zip"
                         sha="53807fa1e51c57c5867679acecab777a23f7de652d697df7755354c792381ca2"; dirs=@("*"); procs=@("plug-in-resynthesizer","plug-in-heal-selection")
                         note="COMMUNITY build (no official Windows binary exists); .scm files identical to upstream v3.0.1" }
  "batcher"         = @{ kind="zip"; gimp="3.0,3.2"; ver="1.2.10"; file="batcher-1.2.10.zip"
                         url="https://github.com/kamilburda/batcher/releases/download/1.2.10/batcher-1.2.10.zip"
                         sha="328ade5b026f4140981edd975f0cf830c3812d5c84dc2534cb55d68c1d1894b7"; dirs=@("batcher"); procs=@("plug-in-batch-export-images","plug-in-batch-convert") }
  "adjustment-layer"= @{ kind="rawfile"; gimp="3.0,3.2"; ver="cc07757"; file="adjustment-layer-cc07757.py"
                         url="https://raw.githubusercontent.com/bunnywaffle/adjustment-layer/cc07757c05dade6b0aa2cb8e7356efd9e08f8cdf/adjustment-layer.py"
                         sha="5fa33102415b7bcc05f1e45cd7a0335d54c6f4e663db1bec27942bd5f76de7aa"; dest="adjustment-layer\adjustment-layer.py"
                         procs=@("plug-in-adjustment-layer-curves","plug-in-layer-effect-drop-shadow") }
  "photogimp"       = @{ kind="config"; gimp="3.0,3.2"; ver="eca3a8f"; file="photogimp-eca3a8f.tar.gz"
                         url="https://github.com/Diolinux/PhotoGIMP/archive/eca3a8f57b9944c063d043ce7c07524107b5292d.tar.gz"
                         sha="beab281ed1281219bb0b994df4e66e8ff107e54dad943644d077205a325c7d99"; procs=@()
                         note="opt-in; overwrites layout/shortcuts/tool presets; keeps gimprc keys: language, theme, icons, import-raw-plug-in" }
}
$Sets = @{ "ours"=@("fsep_oneclick","dnb_setup","batch_export","mesh_liquify","spot_heal","dnb_flow","subject_mask"); "third-party"=@("gmic","resynthesizer","batcher","adjustment-layer") }
$Sets["all"] = $Sets["ours"] + $Sets["third-party"]

if ($List) {
  $C.Keys | ForEach-Object { $d = $C[$_]; [pscustomobject]@{ Component=$_; Version=$d.ver; GIMP=$d.gimp; Kind=$d.kind; Note=$d.note } } | Format-Table -AutoSize -Wrap
  exit 0
}
$Sel = @(); foreach ($x in $Components) { $Sel += $x.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
if ($Only) { $Sel += $Sets[$Only] }
$Sel = @($Sel | Select-Object -Unique)
if (-not $Sel) { [Console]::Error.WriteLine("Nothing selected. Choose components with -Components a,b,c (see -List) or -Only ours|third-party|all."); exit 64 }
$bad = @($Sel | Where-Object { -not $C.Contains($_) }); if ($bad) { [Console]::Error.WriteLine("Unknown component(s): $($bad -join ', ') (see -List)"); exit 64 }

$Vers = if ($Gimp -eq "all") { @("3.0","3.2") | Where-Object { Test-Path (Join-Path $env:APPDATA "GIMP\$_") } } else { @($Gimp) }
if (-not $Vers) { [Console]::Error.WriteLine("No GIMP 3.x profile found in $env:APPDATA\GIMP. Start GIMP once, or pass -Gimp 3.0 / -Gimp 3.2."); exit 64 }

function Do-It($desc, [scriptblock]$sb) { if ($DryRun) { Write-Host "    [dry-run] $desc" } else { Write-Host "    + $desc"; & $sb } }
function Sha($p) { if (Test-Path -LiteralPath $p -PathType Leaf) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower() } else { "" } }
function Fetch($d) {
  $f = Join-Path $CacheDir $d.file
  if ((Sha $f) -eq $d.sha) { Write-Host "    cached $($d.file) (sha256 ok)"; return $f }
  New-Item -ItemType Directory -Force $CacheDir | Out-Null
  Write-Host "    download $($d.url)"
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) { & $curl.Source -fL --retry 3 --connect-timeout 30 -o "$f.part" $d.url; if ($LASTEXITCODE -ne 0) { Remove-Item -Force "$f.part" -ErrorAction SilentlyContinue; throw "download failed (curl $LASTEXITCODE): $($d.url) -- download it yourself (browser/mirror) into $CacheDir as $($d.file) and re-run" } }
  else { Invoke-WebRequest -UseBasicParsing -Uri $d.url -OutFile "$f.part" }
  $h = Sha "$f.part"
  if ($h -ne $d.sha) { Remove-Item -Force "$f.part"; throw "sha256 mismatch for $($d.file): got $h, expected $($d.sha)" }
  Move-Item -Force "$f.part" $f; return $f
}
function State-Get($prof) { $s = @{}; $p = Join-Path $prof "gimp-bundle-installed.txt"
  if (Test-Path $p) { Get-Content $p | ForEach-Object { $c = $_.Split("|"); if ($c.Count -ge 3) { $s[$c[0]] = $c } } }; return $s }
function State-Set($prof, $id, $d, $paths) { $s = State-Get $prof; $s[$id] = @($id, $d.ver, $d.sha, ($paths -join ";"))
  $lines = $s.Keys | Sort-Object | ForEach-Object { $s[$_] -join "|" }
  [IO.File]::WriteAllLines((Join-Path $prof "gimp-bundle-installed.txt"), [string[]]$lines, $Utf8) }
function Preserve-Gimprc($rc, $oldText) {
  # Same rule as installer/bundle.py: put back the user's single-line settings for $PreserveKeys; drop overlay lines for keys the user never set.
  if (-not (Test-Path $rc)) { return @() }
  $old = [ordered]@{}
  foreach ($line in ($oldText -split "`r?`n")) { if ($line -match '^\(([\w-]+)\s.*\)\s*$' -and $PreserveKeys -contains $Matches[1]) { $old[$Matches[1]] = $line } }
  $out = New-Object System.Collections.Generic.List[string]; $done = @{}
  foreach ($line in ([IO.File]::ReadAllText($rc, $Utf8) -split "`r?`n")) {
    if ($line -match '^\(([\w-]+)[\s)]' -and $PreserveKeys -contains $Matches[1]) {
      $k = $Matches[1]; if ($old.Contains($k) -and -not $done[$k]) { $out.Add($old[$k]); $done[$k] = $true }; continue }
    $out.Add($line)
  }
  foreach ($k in $old.Keys) { if (-not $done[$k]) { $at = if ($out.Count -and $out[0].StartsWith("#")) { 1 } else { 0 }; $out.Insert($at, $old[$k]); $done[$k] = $true } }
  [IO.File]::WriteAllText("$rc.new", ($out -join "`n"), $Utf8); Move-Item -Force "$rc.new" $rc
  return @($done.Keys | Sort-Object)
}

if ((Get-Process -Name "gimp*" -ErrorAction SilentlyContinue) -and $env:GIMP_BUNDLE_IGNORE_RUNNING -ne "1") {   # override only for tests against a scratch APPDATA
  if ($Sel -contains "photogimp" -and -not $DryRun) { [Console]::Error.WriteLine("GIMP is running: close it first (it rewrites gimprc/sessionrc on exit and would undo PhotoGIMP)."); exit 75 }
  Write-Warning "GIMP is running; restart it afterwards (not killing it)."
}
$rows = @(); $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($v in $Vers) {
  $prof = Join-Path $env:APPDATA "GIMP\$v"; $pd = Join-Path $prof "plug-ins"
  if (Test-Path $prof) {
    $bk = Join-Path $BackupDir "gimp-config-$v-$stamp.zip"
    Do-It "backup $prof -> $bk" { New-Item -ItemType Directory -Force $BackupDir | Out-Null; Compress-Archive -Path "$prof\*" -DestinationPath $bk }
  }
  $state = State-Get $prof
  foreach ($id in $Sel) {
    $d = $C[$id]
    if (($d.gimp.Split(",")) -notcontains $v) { $rows += [pscustomobject]@{ GIMP=$v; Component=$id; Version=$d.ver; Action="skipped (no Windows build for GIMP $v)"; Registered="-" }; continue }
    $act = "ok (up to date)"
    try {
      if ($d.kind -eq "ours") {
        $dst = Join-Path $pd $id; $need = [bool]$Reinstall
        foreach ($f in $d.files) { if ((Sha (Join-Path $Repo $f)) -ne (Sha (Join-Path $dst (Split-Path $f -Leaf)))) { $need = $true } }
        if ($need) { Do-It "install $id -> $dst" { New-Item -ItemType Directory -Force $dst | Out-Null; foreach ($f in $d.files) { Copy-Item -Force (Join-Path $Repo $f) $dst } }; $act = "installed" }
      } else {
        $cur = $state[$id]
        $need = $Reinstall -or -not $cur -or $cur[2] -ne $d.sha -or ($cur.Count -ge 4 -and ($cur[3].Split(";") | Where-Object { $_ -and -not (Test-Path (Join-Path $prof $_)) }))
        if ($need) {
          if ($DryRun) { $src = if ((Sha (Join-Path $CacheDir $d.file)) -eq $d.sha) { "cached" } else { "download" }; Write-Host "    [dry-run] $id $($d.ver): $src $($d.file) (sha256 $($d.sha.Substring(0,12))...) and install" }
          else {
            $f = Fetch $d; $tmp = Join-Path $env:TEMP ("gimp-bundle-" + [guid]::NewGuid().ToString("N")); New-Item -ItemType Directory $tmp | Out-Null
            try {
              if ($d.kind -eq "zip") {
                Expand-Archive -LiteralPath $f -DestinationPath $tmp
                $tops = if ($d.dirs -contains "*") { Get-ChildItem -Directory $tmp } else { $d.dirs | ForEach-Object { Get-Item (Join-Path $tmp $_) } }
                New-Item -ItemType Directory -Force $pd | Out-Null; $paths = @()
                foreach ($t in $tops) { $dst = Join-Path $pd $t.Name; if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
                  Copy-Item -Recurse $t.FullName $dst; $paths += "plug-ins\$($t.Name)"; Write-Host "    + $id -> $dst" }
                State-Set $prof $id $d $paths
              } elseif ($d.kind -eq "rawfile") {
                $dst = Join-Path $pd $d.dest; New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null; Copy-Item -Force $f $dst
                Write-Host "    + $id -> $dst"; State-Set $prof $id $d @("plug-ins\$($d.dest)")
              } elseif ($d.kind -eq "config") {
                & tar.exe -xzf $f -C $tmp; if ($LASTEXITCODE -ne 0) { throw "tar failed" }
                $root = (Get-ChildItem -Directory $tmp | Select-Object -First 1).FullName
                $src = @("$root\.config\GIMP\$v", "$root\.config\GIMP\3.0") | Where-Object { Test-Path $_ } | Select-Object -First 1
                if (-not $src) { throw "no .config\GIMP\<ver> in PhotoGIMP archive" }
                Write-Host "    PhotoGIMP source dir: $($src.Substring($root.Length + 1))"
                New-Item -ItemType Directory -Force $prof, $BackupDir | Out-Null
                $pre = Join-Path $BackupDir "photogimp-pre-$v-$stamp.zip"
                if (Get-ChildItem $prof) { Compress-Archive -Path "$prof\*" -DestinationPath $pre; Write-Host "    dedicated pre-PhotoGIMP backup: $pre" }
                $rc = Join-Path $prof "gimprc"; $oldRc = if (Test-Path $rc) { [IO.File]::ReadAllText($rc, $Utf8) } else { "" }
                Copy-Item -Recurse -Force "$src\*" $prof
                $kept = Preserve-Gimprc $rc $oldRc
                if ($kept) { Write-Host "    kept your gimprc settings: $($kept -join ', ')" }
                State-Set $prof $id $d @(Get-ChildItem $src | ForEach-Object { $_.Name })
              }
            } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
          }
          $act = if ($DryRun) { "would-install" } else { "installed" }
        }
      }
    } catch { $act = "FAILED: $($_.Exception.Message)" }
    $rc2 = Join-Path $prof "pluginrc"
    $reg = if (-not $d.procs) { "-" } elseif ((Test-Path $rc2) -and -not ($d.procs | Where-Object { -not (Select-String -Quiet -SimpleMatch "(proc-def `"$_`"" $rc2) })) { "yes" } else { "not yet (start GIMP once)" }
    $rows += [pscustomobject]@{ GIMP=$v; Component=$id; Version=$d.ver; Action=$act; Registered=$reg }
  }
}
$rows | Format-Table -AutoSize -Wrap
if ($rows | Where-Object { $_.Action -like "FAILED*" }) { exit 1 }
