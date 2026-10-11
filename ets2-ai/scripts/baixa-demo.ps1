# Baixa a DEMO OFICIAL do ETS2 (SCS, freeware, AppID 231120) — 3 rotas.
# Roda no job demo-real (Windows). Sintaxe conservadora: uma linha por
# comando, sem continuacao de backtick, regex SEM aspa simples interna
# (PS single-quote nao tem escape — usa aspas duplas com "" dobrado).
$ErrorActionPreference = "Continue"
$alvo = "C:\ets2demo\bin\win_x64\eurotrucks2.exe"
New-Item -ItemType Directory -Force -Path "C:\ets2demo" | Out-Null
function Log($m) { Write-Host ("[demo] " + $m) }

# ---- ROTA 1: steamcmd anonimo em 2 FASES (licenca, depois update) ----
$sc = "C:\steamcmd"
try {
  New-Item -ItemType Directory -Force -Path $sc | Out-Null
  Invoke-WebRequest "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" -OutFile "$sc\steamcmd.zip"
  Expand-Archive "$sc\steamcmd.zip" -DestinationPath $sc -Force
  & "$sc\steamcmd.exe" +login anonymous +app_license_request 231120 +quit *> "$sc\fase1.log"
  Get-Content "$sc\fase1.log" -ErrorAction SilentlyContinue | Select-Object -Last 6 | ForEach-Object { Log "steamcmd fase1: $_" }
  & "$sc\steamcmd.exe" +force_install_dir C:\ets2demo +login anonymous +app_update 231120 validate +quit *> "$sc\fase2.log"
  Get-Content "$sc\fase2.log" -ErrorAction SilentlyContinue | Select-Object -Last 8 | ForEach-Object { Log "steamcmd fase2: $_" }
} catch { Log ("steamcmd: " + $_.Exception.Message) }
if (Test-Path $alvo) { Log "ROTA 1 (steamcmd) OK"; exit 0 }

# ---- ROTA 2: DepotDownloader (GitHub, tenta anonimo) ----
try {
  $rel = Invoke-RestMethod "https://api.github.com/repos/SteamRE/DepotDownloader/releases/latest"
  $asset = $rel.assets | Where-Object { $_.name -match "x64" -and $_.name -match "zip" -and $_.name -notmatch "osx|linux" } | Select-Object -First 1
  Log ("DepotDownloader: " + $asset.name)
  Invoke-WebRequest $asset.browser_download_url -OutFile "C:\dd.zip"
  Expand-Archive "C:\dd.zip" -DestinationPath "C:\dd" -Force
  $dd = Get-ChildItem "C:\dd" -Recurse -Filter "*.exe" | Select-Object -First 1
  if ($dd) {
    & $dd.FullName -app 231120 -dir C:\ets2demo -validate *> "C:\dd\dd.log"
    Get-Content "C:\dd\dd.log" -ErrorAction SilentlyContinue | Select-Object -Last 10 | ForEach-Object { Log ("depotdl: " + $_) }
  }
} catch { Log ("DepotDownloader: " + $_.Exception.Message) }
if (Test-Path $alvo) { Log "ROTA 2 (DepotDownloader) OK"; exit 0 }

# ---- ROTA 3: instalador OFFLINE da demo (TechSpot, freeware SCS) ----
try {
  $ua = @{ "UserAgent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"; "Referer" = "https://www.techspot.com/downloads/5653-euro-truck-simulator-2-demo.html" }
  $html = ""
  foreach ($u in @(
    "https://www.techspot.com/downloads/downloadnow/5653/?evp=be74c2e849e2f76652741e2a8a90963f&file=6489",
    "https://www.techspot.com/downloads/downloadnow/5653/?file=6489")) {
    try { $html = (Invoke-WebRequest @ua -Uri $u -MaximumRedirection 5 -UseBasicParsing).Content; if ($html) { break } } catch {}
  }
  # link DIRETO (downloadnowfile) com token fresco — regex em aspas duplas
  $rx = "https?://[^""'<>\s]*downloadnowfile[^""'<>\s]*"
  $m = [regex]::Matches($html, $rx) | ForEach-Object { $_.Value } | Select-Object -Unique
  Log ("TechSpot downloadnowfile: " + ($m -join " | ") + " (html " + $html.Length + " bytes)")
  if (-not $m) {
    $rx2 = "https?://[^""'<>\s]+\.exe"
    $m = [regex]::Matches($html, $rx2) | ForEach-Object { $_.Value } | Select-Object -Unique
    Log ("TechSpot .exe direto: " + ($m -join " | "))
  }
  if ($m) {
    Invoke-WebRequest @ua -Uri $m[0] -OutFile "C:\demo-setup.exe" -MaximumRedirection 10
    Log ("instalador: " + [math]::Round((Get-Item C:\demo-setup.exe).Length / 1MB) + " MB")
    # instaladores SCS: /S (NSIS) ou /VERYSILENT (Inno); tenta ambos
    foreach ($flag in @("/S", "/VERYSILENT")) {
      $p = Start-Process -FilePath "C:\demo-setup.exe" -ArgumentList $flag -Wait -PassThru
      if (Test-Path $alvo) { break }
      $found = Get-ChildItem "C:\Program Files\Euro Truck Simulator 2 Demo", "C:\Program Files (x86)\Euro Truck Simulator 2 Demo", "$env:LOCALAPPDATA\Programs" -Recurse -Filter "eurotrucks2.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($found) {
        New-Item -ItemType Directory -Force "C:\ets2demo\bin\win_x64" | Out-Null
        Copy-Item $found.FullName "C:\ets2demo\bin\win_x64\eurotrucks2.exe" -Force
        $raiz = Split-Path (Split-Path $found.FullName -Parent) -Parent
        Get-ChildItem $raiz -File | Copy-Item "C:\ets2demo\" -Force -ErrorAction SilentlyContinue
        if (Test-Path (Join-Path $raiz "bin\win_x64")) {
          Copy-Item (Join-Path $raiz "bin\win_x64\*") "C:\ets2demo\bin\win_x64\" -Recurse -Force -ErrorAction SilentlyContinue
        }
        break
      }
    }
  }
} catch { Log ("TechSpot: " + $_.Exception.Message) }
if (Test-Path $alvo) { Log "ROTA 3 (instalador offline) OK"; exit 0 }

# ---- tudo falhou: resumo em ANOTACAO (legivel pela API) ----
$f1 = (Get-Content "$sc\fase1.log" -ErrorAction SilentlyContinue | Select-Object -Last 5) -join " | "
$f2 = (Get-Content "$sc\fase2.log" -ErrorAction SilentlyContinue | Select-Object -Last 5) -join " | "
$ddl = (Get-Content "C:\dd\dd.log" -ErrorAction SilentlyContinue | Select-Object -Last 5) -join " | "
Write-Host ("::error::ROTA1 steamcmd fase1: " + $f1 + " /// fase2: " + $f2 + " /// ROTA2 depot: " + $ddl)
throw "nao consegui baixar a demo oficial"
