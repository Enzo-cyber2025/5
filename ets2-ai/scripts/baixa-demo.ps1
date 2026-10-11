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
  $asset = $rel.assets | Where-Object { $_.name -match "x64" -and $_.name -match "zip" -and $_.name -notmatch "osx|macos|linux" } | Select-Object -First 1
  Log ("DepotDownloader: " + $asset.name)
  Invoke-WebRequest $asset.browser_download_url -OutFile "C:\dd.zip"
  Expand-Archive "C:\dd.zip" -DestinationPath "C:\dd" -Force
  $dd = Get-ChildItem "C:\dd" -Recurse -Filter "*.exe" | Select-Object -First 1
  if ($dd) {
    Log ("exe: " + $dd.FullName)
    & $dd.FullName -app 231120 -dir C:\ets2demo -validate *> "C:\dd\dd.log"
    $cod = $LASTEXITCODE
    Log ("DepotDownloader exit: $cod")
    Get-Content "C:\dd\dd.log" -ErrorAction SilentlyContinue | Select-Object -Last 15 | ForEach-Object { Log ("depotdl: " + $_) }
  } else {
    Log "DepotDownloader: nenhum exe no zip"
  }
} catch { Log ("DepotDownloader: " + $_.Exception.Message) }
if (Test-Path $alvo) { Log "ROTA 2 (DepotDownloader) OK"; exit 0 }

# ---- ROTA 3: instalador OFFLINE da demo (TechSpot, freeware SCS) ----
# Fluxo do token (o evp expira e e por visitante):
#   1. pagina da demo  ->  link downloadnow/5653/?evp=<fresco>
#   2. pagina downloadnow  ->  link downloadnowfile/5653/?evp=<outro>
#   3. downloadnowfile  ->  instalador .exe (542 MB, v1.40.4.8)
try {
  $ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  $ref = "https://www.techspot.com/downloads/5653-euro-truck-simulator-2-demo.html"
  # --compressed: Cloudflare pode forcAR gzip (167 KB de bytes sem decode
  # no run 38174907081 — regex nao casava NADA, nem .exe)
  $rxcurl = @("-sL", "--compressed", "--max-time", "90", "-A", $ua)

  # 1) pagina da demo -> URL downloadnow com evp FRESCO
  $pag = & curl.exe @rxcurl -H "Referer: https://www.techspot.com/" $ref 2>$null
  $txtp = $pag -join " "
  Log ("pagina da demo: " + $txtp.Length + " chars")
  $rxnow = "https?://[^" + '"' + "'" + "<>\s]*downloadnow/5653/[^" + '"' + "'" + "<>\s]*"
  $m1 = [regex]::Matches($txtp, $rxnow) | ForEach-Object { $_.Value } | Select-Object -Unique
  if (-not $m1) {
    $m1 = [regex]::Matches($txtp, "/downloads/downloadnow/5653/[^" + '"' + "'" + "<>\s]*") | ForEach-Object { "https://www.techspot.com" + $_.Value } | Select-Object -Unique
  }
  Log ("downloadnow (evp fresco): " + ($m1 -join " | "))

  # 2) pagina downloadnow -> link DIRETO downloadnowfile
  $html = ""
  if ($m1) {
    $html = & curl.exe @rxcurl -H "Referer: $ref" $m1[0] 2>$null
  }
  if (-not $html) {
    # fallback: URL antiga com evp vencido (as vezes ainda serve)
    $html = & curl.exe @rxcurl -H "Referer: $ref" "https://www.techspot.com/downloads/downloadnow/5653/?file=6489" 2>$null
  }
  $txt = $html -join " "
  Log ("pagina downloadnow: " + $txt.Length + " chars")
  $rx = "https?://[^" + '"' + "'" + "<>\s]*downloadnowfile[^" + '"' + "'" + "<>\s]*"
  $m = [regex]::Matches($txt, $rx) | ForEach-Object { $_.Value } | Select-Object -Unique
  if (-not $m) {
    $rx2 = "https?://[^" + '"' + "'" + "<>\s]+\.exe"
    $m = [regex]::Matches($txt, $rx2) | ForEach-Object { $_.Value } | Select-Object -Unique
    Log ("TechSpot .exe direto: " + ($m -join " | "))
  } else {
    Log ("TechSpot downloadnowfile: " + ($m -join " | "))
  }
  if (-not $m -and $txt.Length -gt 0) {
    # DEBUG: primeiros chars + menções a download (descoberta iterativa)
    Log ("HTML head: " + $txt.Substring(0, [math]::Min(600, $txt.Length)))
    $downs = [regex]::Matches($txt, "[a-zA-Z0-9/_.:-]{0,60}download[a-zA-Z0-9/_.?=-]{0,80}") | ForEach-Object { $_.Value } | Select-Object -Unique -First 12
    Log ("mencoes a download: " + ($downs -join " | "))
  }
  if ($m) {
    & curl.exe -sL --compressed --max-time 1500 -A $ua -e $ref -o "C:\demo-setup.exe" $m[0]
    Log ("instalador: " + [math]::Round((Get-Item C:\demo-setup.exe -ErrorAction SilentlyContinue).Length / 1MB) + " MB")
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
