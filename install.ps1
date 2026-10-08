# gimp-retouch-plugins installer for Windows -- tested on Windows 11 + GIMP 3.2.6 (headless, 2026-10-08); GUI dialogs 尚未人工验证
# Installs the components YOU choose into %APPDATA%\GIMP\<ver>\ (user profile only, no admin needed):
#   ours:        fsep_oneclick, dnb_setup, batch_export, mesh_liquify, spot_heal, dnb_flow, subject_mask, action_record, portrait_brush
#   third-party: gmic, resynthesizer, batcher, adjustment-layer    (downloaded, sha256-checked)
#   opt-in:      photogimp  (overwrites layout/shortcuts/tool presets; keeps your language/theme/icon gimprc settings)
#   app:         rawtherapee (official per-user installer, no admin, into -RawTherapeeDir\<version>; GIMP's RAW importer is pointed at it)
#   helper:      helper-python (private embeddable Python 3.12 + numpy + opencv-python-headless in -HelperPythonDir, no admin;
#                GIMP's own Python cannot load OpenCV wheels. subject_mask needs it; mesh_liquify's face mode uses it.)
#   Requirements are added automatically: subject_mask -> mesh_liquify (face model) + helper-python; spot_heal -> resynthesizer.
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -List
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Components fsep_oneclick,gmic,batcher [-Gimp 3.2] [-BackupDir D:\gimp-bundle-backups]
#              [-CacheDir D:\Downloads\gimp-bundle-cache] [-RawTherapeeDir D:\RawTherapee] [-HelperPythonDir D:\Python\retouch-py312]
#              [-Reinstall] [-DryRun]
#   -Only ours|third-party|all  = shortcut for a component set (photogimp is never included implicitly; name it in -Components).
#   -Gimp all = every version that already has a profile in %APPDATA%\GIMP; a fresh GIMP (never started) needs -Gimp 3.2 explicitly.
#   -CacheDir: downloads are kept/reused there; a file already present with the right sha256 is not downloaded again
#              (useful when GitHub is slow: put the files there yourself). Files with mirrors (Python, wheels) try each URL in turn.
param(
  [ValidateSet("3.0","3.2","all")][string]$Gimp = "all",
  [ValidateSet("","ours","third-party","all")][string]$Only = "",
  [string[]]$Components = @(),
  [string]$BackupDir = (Join-Path $env:USERPROFILE "gimp-bundle-backups"),
  [string]$CacheDir = (Join-Path $env:TEMP "gimp-bundle-cache"),
  [string]$RawTherapeeDir = (Join-Path $env:LOCALAPPDATA "Programs\RawTherapee"),
  [string]$HelperPythonDir = (Join-Path $env:LOCALAPPDATA "Programs\retouch-python"),
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
  "action_record"   = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("action_record\action_record.py","action_record\store.py","action_record\layers.py"); procs=@("python-fu-action-record-start","python-fu-action-record-stop","python-fu-action-play") }
  "portrait_brush"  = @{ kind="ours"; gimp="3.0,3.2"; ver="repo"; files=@("portrait_brush\portrait_brush.py"); procs=@("python-fu-portrait-brush")
                         brushdir="portrait-retouch"; brushes=@("portrait_brush\brushes\portrait-soft-round.vbr","portrait_brush\brushes\portrait-skin-pores.gbr","portrait_brush\brushes\portrait-hair-strand.gih") }
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
  "rawtherapee"     = @{ kind="app"; gimp="3.0,3.2"; ver="5.13"; file="RawTherapee_5.13_win64_x86_64_release.exe"
                         url="https://github.com/RawTherapee/RawTherapee/releases/download/5.13/RawTherapee_5.13_win64_x86_64_release.exe"
                         sha="d27df7ebde717c5efa114338a4b1cf1c426a439e5a1a92e142e87868cbe45383"; procs=@()
                         note="separate app (sha256 = GitHub release digest); per-user install into -RawTherapeeDir\5.13 + desktop/Start Menu shortcuts + HKCU App Paths (what GIMP's file-rawtherapee reads); sets gimprc import-raw-plug-in" }
  "helper-python"   = @{ kind="pyenv"; gimp="3.0,3.2"; ver="3.12.10+np2.5.3+cv5.0.0"; procs=@()
                         note="private Python for the OpenCV helpers (subject_mask, mesh_liquify face mode); writes retouch-helper-python.txt into the GIMP profile"
                         parts=@(
                           @{ file="python-3.12.10-embed-amd64.zip"; sha="4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
                              urls=@("https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
                                     "https://registry.npmmirror.com/-/binary/python/3.12.10/python-3.12.10-embed-amd64.zip",
                                     "https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-embed-amd64.zip") },
                           @{ file="numpy-2.5.3-cp312-cp312-win_amd64.whl"; sha="0a59a421a32580a009e8a1751345bf829631b990dc1794b80514ab722b435def"; pypi="numpy" },
                           @{ file="opencv_python_headless-5.0.0.93-cp37-abi3-win_amd64.whl"; sha="829717b6a95554f273e49e357cee3b3a2a26b6f4842fbc1bed2b45bdd8f87e0e"; pypi="opencv-python-headless" }) }
}
$Requires = @{ "subject_mask"=@("mesh_liquify","helper-python"); "spot_heal"=@("resynthesizer") }
$Recommends = @{ "mesh_liquify"="helper-python (face mode)" }
$Sets = @{ "ours"=@("fsep_oneclick","dnb_setup","batch_export","mesh_liquify","spot_heal","dnb_flow","subject_mask","action_record","portrait_brush"); "third-party"=@("gmic","resynthesizer","batcher","adjustment-layer") }
$Sets["all"] = $Sets["ours"] + $Sets["third-party"]

if ($List) {
  $C.Keys | ForEach-Object { $d = $C[$_]; [pscustomobject]@{ Component=$_; Version=$d.ver; GIMP=$d.gimp; Kind=$d.kind; Note=$d.note } } | Format-Table -AutoSize -Wrap
  exit 0
}
$Sel = @(); foreach ($x in $Components) { $Sel += $x.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
if ($Only) { $Sel += $Sets[$Only] }
$Sel = @($Sel | Select-Object -Unique)
foreach ($x in @($Sel)) { foreach ($r in @($Requires[$x])) { if ($r -and $Sel -notcontains $r) { $Sel += $r; Write-Host "  + $r (needed by $x)" } } }
foreach ($x in @($Sel)) { if ($Recommends[$x] -and $Sel -notcontains ($Recommends[$x].Split(" ")[0])) { Write-Host "  hint: $x works better with $($Recommends[$x])" } }
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
  $urls = if ($d.urls) { @($d.urls) } else { @($d.url) }
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue; $why = @()
  foreach ($u in $urls) {
    Write-Host "    download $u"
    Remove-Item -Force "$f.part" -ErrorAction SilentlyContinue
    try {
      if ($curl) { & $curl.Source -fL --retry 2 --connect-timeout 20 -o "$f.part" $u; if ($LASTEXITCODE -ne 0) { throw "curl $LASTEXITCODE" } }
      else { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile "$f.part" }
    } catch { $why += "$u ($($_.Exception.Message))"; continue }
    $h = Sha "$f.part"
    if ($h -eq $d.sha) { Move-Item -Force "$f.part" $f; return $f }
    $why += "$u (sha256 mismatch: got $h)"
  }
  Remove-Item -Force "$f.part" -ErrorAction SilentlyContinue
  throw "download failed for $($d.file): $($why -join '; ') -- put the file (sha256 $($d.sha)) into $CacheDir yourself and re-run"
}
function Wheel-Urls($p) {   # same /packages/... path on PyPI and its mirrors
  $tail = $null
  foreach ($j in "https://pypi.org/pypi/$($p.pypi)/json", "https://mirrors.aliyun.com/pypi/web/json/$($p.pypi)") {
    try { $r = Invoke-RestMethod -TimeoutSec 20 -Uri $j; $u = @($r.urls + ($r.releases.PSObject.Properties | ForEach-Object { $_.Value })) | Where-Object { $_.filename -eq $p.file } | Select-Object -First 1
          if ($u) { $tail = ([uri]$u.url).AbsolutePath -replace '^.*?/packages/', ''; break } } catch { }
  }
  $out = @()
  if ($tail) { $out += "https://files.pythonhosted.org/packages/$tail", "https://mirrors.aliyun.com/pypi/packages/$tail", "https://pypi.tuna.tsinghua.edu.cn/packages/$tail" }
  foreach ($idx in "https://mirrors.aliyun.com/pypi/simple", "https://pypi.tuna.tsinghua.edu.cn/simple") {   # PyPI JSON blocked: read the simple index
    try { $h = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri "$idx/$($p.pypi)/").Content
          $m = [regex]::Match($h, 'href="([^"#]*' + [regex]::Escape($p.file) + ')')
          if ($m.Success) { $out += ([uri]::new([uri]"$idx/$($p.pypi)/", $m.Groups[1].Value)).AbsoluteUri } } catch { }
  }
  return @($out | Select-Object -Unique)
}
function Install-HelperPython($d) {
  $py = Join-Path $HelperPythonDir "python.exe"; $mark = Join-Path $HelperPythonDir "retouch-helper-version.txt"
  if (-not $Reinstall -and (Test-Path $py) -and (Test-Path $mark) -and ((Get-Content $mark -Raw).Trim() -eq $d.ver)) {
    & $py -c "import cv2, numpy" 2>$null; if ($LASTEXITCODE -eq 0) { return $false } }
  $files = @()
  foreach ($p in $d.parts) {
    $q = @{ file=$p.file; sha=$p.sha; urls=$p.urls }
    if ($p.pypi -and -not ((Sha (Join-Path $CacheDir $p.file)) -eq $p.sha)) { $q.urls = Wheel-Urls $p; if (-not $q.urls) { throw "no download URL found for $($p.file)" } }
    $files += Fetch $q
  }
  Write-Host "    + helper Python $($d.ver) -> $HelperPythonDir"
  if (Test-Path $HelperPythonDir) { Remove-Item -Recurse -Force $HelperPythonDir }
  New-Item -ItemType Directory -Force $HelperPythonDir | Out-Null
  Expand-Archive -LiteralPath $files[0] -DestinationPath $HelperPythonDir
  $sp = Join-Path $HelperPythonDir "Lib\site-packages"; New-Item -ItemType Directory -Force $sp | Out-Null
  foreach ($w in $files[1..($files.Count - 1)]) {   # a wheel is a zip of site-packages content; no pip needed
    $z = Join-Path $env:TEMP ("whl-" + [guid]::NewGuid().ToString("N") + ".zip"); Copy-Item $w $z
    try { Expand-Archive -LiteralPath $z -DestinationPath $sp -Force } finally { Remove-Item -Force $z } }
  $pth = Get-ChildItem $HelperPythonDir -Filter "python*._pth" | Select-Object -First 1   # embeddable Python ignores PYTHONPATH; list site-packages here
  $lines = @(Get-Content $pth.FullName | Where-Object { $_ -notmatch '^#?\s*import site' }) + @("Lib\site-packages", "import site")
  [IO.File]::WriteAllLines($pth.FullName, [string[]]$lines, $Utf8)
  $v = & $py -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)" 2>&1
  if ($LASTEXITCODE -ne 0) { throw "helper Python cannot import cv2: $v" }
  Write-Host "    helper Python ok: opencv/numpy $v"
  [IO.File]::WriteAllText($mark, $d.ver, $Utf8); return $true
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

function Install-RawTherapee($d) {
  $dir = Join-Path $RawTherapeeDir $d.ver
  $cli = Join-Path $dir "rawtherapee-cli.exe"; $about = Join-Path $dir "AboutThisBuild.txt"; $new = $false
  $have = (Test-Path $cli) -and (Test-Path $about) -and (Select-String -Quiet -SimpleMatch "Version: $($d.ver)" $about)
  if (-not $have -or $Reinstall) {
    $f = Fetch $d
    Write-Host "    + RawTherapee $($d.ver) -> $dir (per-user, silent; Inno Setup PrivilegesRequired=none, no UAC)"
    New-Item -ItemType Directory -Force $CacheDir | Out-Null
    $p = Start-Process -FilePath $f -PassThru -Wait -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',"/DIR=`"$dir`"",'/TASKS="userinstall,desktopicon"',"/LOG=`"$(Join-Path $CacheDir 'rawtherapee-install.log')`""
    if ($p.ExitCode -ne 0 -or -not (Test-Path $cli)) { throw "RawTherapee installer failed (exit $($p.ExitCode)); log: $(Join-Path $CacheDir 'rawtherapee-install.log')" }
    $new = $true
  }
  # GIMP's file-rawtherapee: env RAWTHERAPEE_EXECUTABLE, else HKCU then HKLM "...\App Paths\rawtherapee.exe" (and rawtherapee-cli.exe), else PATH.
  # The installer's userinstall task writes these keys; make sure they point at this copy.
  foreach ($exe in "rawtherapee.exe","rawtherapee-cli.exe") {
    $k = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\$exe"
    if ((Get-ItemProperty $k -ErrorAction SilentlyContinue).'(default)' -ne (Join-Path $dir $exe)) {
      New-Item -Force $k | Out-Null; Set-ItemProperty $k -Name '(default)' -Value (Join-Path $dir $exe); $new = $true } }
  $v = (& $cli -h 2>&1 | Select-String -Pattern 'RawTherapee, version [0-9.]+' | Select-Object -First 1)
  if ($v) { Write-Host "    $($v.Matches[0].Value) ($cli)" }
  return $new
}
function Set-RawImporter($prof) {
  $rc = Join-Path $prof "gimprc"; $line = '(import-raw-plug-in "${gimp_plug_in_dir}\\plug-ins\\file-rawtherapee\\file-rawtherapee.exe")'
  $t = if (Test-Path $rc) { [IO.File]::ReadAllText($rc, $Utf8) } else { "" }
  if ($t.Contains($line)) { return $false }
  if ($t -match '(?m)^\(import-raw-plug-in [^\r\n]*') { $t = [regex]::Replace($t, '(?m)^\(import-raw-plug-in [^\r\n]*', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line }) }
  else { $t = $line + "`n" + $t }
  [IO.File]::WriteAllText($rc, $t, $Utf8); return $true
}

$running = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'gimp%'" -ErrorAction SilentlyContinue)   # Get-Process misses gimp-3.exe here
if ($running -and $env:GIMP_BUNDLE_IGNORE_RUNNING -ne "1") {   # override only for tests against a scratch APPDATA
  if (($Sel -contains "photogimp" -or $Sel -contains "rawtherapee") -and -not $DryRun) { [Console]::Error.WriteLine("GIMP is running: close it first (it rewrites gimprc/sessionrc on exit and would undo photogimp/rawtherapee settings)."); exit 75 }
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
      if ($d.kind -eq "pyenv") {
        if ($DryRun) { Write-Host "    [dry-run] helper Python $($d.ver) -> $HelperPythonDir; $prof\retouch-helper-python.txt"; $act = "would-install" }
        else {
          if (-not $script:pyDone) { if (Install-HelperPython $d) { $act = "installed" }; $script:pyDone = $true }
          $hp = Join-Path $prof "retouch-helper-python.txt"; $want = Join-Path $HelperPythonDir "python.exe"
          if (-not (Test-Path $hp) -or ((Get-Content $hp -Raw).Trim() -ne $want)) { [IO.File]::WriteAllText($hp, $want, $Utf8); Write-Host "    + $hp"; if ($act -notlike "installed*") { $act = "configured" } }
        }
      } elseif ($d.kind -eq "app") {
        if ($DryRun) { Write-Host "    [dry-run] rawtherapee $($d.ver) -> $RawTherapeeDir; gimprc import-raw-plug-in -> file-rawtherapee"; $act = "would-install" }
        else {
          if (-not $script:rtDone) { if (Install-RawTherapee $d) { $act = "installed" }; $script:rtDone = $true }
          if (Set-RawImporter $prof) { Write-Host "    + gimprc: RAW importer -> file-rawtherapee"; if ($act -notlike "installed*") { $act = "configured" } }
        }
      } elseif ($d.kind -eq "ours") {
        $dst = Join-Path $pd $id; $need = [bool]$Reinstall
        foreach ($f in $d.files) { if ((Sha (Join-Path $Repo $f)) -ne (Sha (Join-Path $dst (Split-Path $f -Leaf)))) { $need = $true } }
        $bdst = if ($d.brushdir) { Join-Path $prof "brushes\$($d.brushdir)" } else { $null }   # brush files go to the profile's brushes folder
        if ($bdst) { foreach ($f in $d.brushes) { if ((Sha (Join-Path $Repo $f)) -ne (Sha (Join-Path $bdst (Split-Path $f -Leaf)))) { $need = $true } } }
        if ($need) { Do-It "install $id -> $dst" { New-Item -ItemType Directory -Force $dst | Out-Null; foreach ($f in $d.files) { Copy-Item -Force (Join-Path $Repo $f) $dst }
                       if ($bdst) { New-Item -ItemType Directory -Force $bdst | Out-Null; foreach ($f in $d.brushes) { Copy-Item -Force (Join-Path $Repo $f) $bdst } } }; $act = "installed" }
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
