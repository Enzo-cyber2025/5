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
# Run 38181824100: o URL downloadnow JA REDIRECIONA pro instalador —
# capturar o stdout do curl numa variavel deu OOM (542 MB no buffer do
# PowerShell). Agora o curl escreve DIRETO em arquivo e a gente checa
# se veio binario MZ (instalador) ou HTML (pagina com o proximo link).
try {
  $ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  $ref = "https://www.techspot.com/downloads/5653-euro-truck-simulator-2-demo.html"
  $rxcurl = @("-sL", "--compressed", "-A", $ua)

  # 1) pagina da demo -> URL downloadnow com evp (provado no run anterior)
  $pag = & curl.exe @rxcurl --max-time 90 -H "Referer: https://www.techspot.com/" $ref 2>$null
  $txtp = $pag -join " "
  Log ("pagina da demo: " + $txtp.Length + " chars")
  $rxnow = "https?://[^" + '"' + "'" + "<>\s]*downloadnow/5653/[^" + '"' + "'" + "<>\s]*"
  $m1 = [regex]::Matches($txtp, $rxnow) | ForEach-Object { $_.Value } | Select-Object -Unique
  if (-not $m1) {
    $m1 = [regex]::Matches($txtp, "/downloads/downloadnow/5653/[^" + '"' + "'" + "<>\s]*") | ForEach-Object { "https://www.techspot.com" + $_.Value } | Select-Object -Unique
  }
  Log ("downloadnow: " + ($m1 -join " | "))

  $setup = "C:\demo-setup.exe"
  $stage2 = "C:\demo-stage2.bin"
  # GOTCHA PowerShell: com 1 match so, $m1 e STRING e $m1[0] = 1o
  # CARACTERE ('h' de https://) — run 38255906101: 'Could not resolve
  # host: h'. @() forca array: @($m1)[0] e a URL inteira.
  $url2 = @($m1)[0]
  Log ("URL do estagio 2: " + $url2)
  if ($url2) {
    # 2) BAIXA o downloadnow direto em ARQUIVO — 3 motores:
    #    curl (com exit code logado) -> IWR (streaming p/ disco) -> BITS.
    #    Run 38183604100: curl -o criou 0 bytes sem erro visivel (-s
    #    engoliu); run 38181824100 PROVOU que a URL serve o instalador.
    New-Item -ItemType Directory -Force -Path "C:\dd" | Out-Null
    $w = & curl.exe -sSL --compressed --max-time 1400 -A $ua -H "Referer: $ref" --retry 2 -w "%{http_code} %{size_download} %{url_effective}" -o $stage2 $url2 2> C:\dd\stage2.err
    Log ("curl exit: $LASTEXITCODE | $w")
    $r3 = "curl=$LASTEXITCODE $w"
    if (-not (Test-Path $stage2) -or (Get-Item $stage2).Length -lt 1KB) {
      Log "curl falhou — tentando Invoke-WebRequest (streaming)"
      try {
        Invoke-WebRequest -Uri $url2 -OutFile $stage2 -UserAgent $ua -MaximumRedirection 10 -TimeoutSec 1400
        $r3 += " | IWR ok"
      } catch { Log ("IWR: " + $_.Exception.Message); $r3 += " | IWR: " + $_.Exception.Message }
    }
    if (-not (Test-Path $stage2) -or (Get-Item $stage2).Length -lt 1KB) {
      Log "IWR falhou — tentando BITS"
      try { Start-BitsTransfer -Source $url2 -Destination $stage2; $r3 += " | BITS ok" } catch { Log ("BITS: " + $_.Exception.Message); $r3 += " | BITS: " + $_.Exception.Message }
    }
    $tam = (Get-Item $stage2 -ErrorAction SilentlyContinue).Length
    Log ("estagio 2: " + [math]::Round($tam / 1MB) + " MB")
    $mz = $false
    if ($tam -gt 2) {
      $fs = [System.IO.File]::OpenRead($stage2)
      $b2 = New-Object byte[] 2
      $n = $fs.Read($b2, 0, 2); $fs.Close()
      $mz = ($n -eq 2 -and $b2[0] -eq 0x4D -and $b2[1] -eq 0x5A)
    }
    if ($mz -and $tam -gt 1MB) {
      Log "estagio 2 E o instalador (MZ) — baixado!"
      Move-Item $stage2 $setup -Force
    } else {
      # HTML (ou MZ minusculo): procura o link DIRETO
      if ($tam -lt 5MB) {
        $txt = [System.IO.File]::ReadAllText($stage2)
        $rx = "https?://[^" + '"' + "'" + "<>\s]*downloadnowfile[^" + '"' + "'" + "<>\s]*"
        $m = [regex]::Matches($txt, $rx) | ForEach-Object { $_.Value } | Select-Object -Unique
        if (-not $m) {
          $rx2 = "https?://[^" + '"' + "'" + "<>\s]+\.exe"
          $m = [regex]::Matches($txt, $rx2) | ForEach-Object { $_.Value } | Select-Object -Unique
        }
        Log ("links no estagio 2: " + ($m -join " | "))
        if ($m) {
          $url3 = @($m)[0]
          Log ("URL do arquivo: " + $url3)
          & curl.exe @rxcurl --max-time 1500 -e $ref -o $setup $url3
        }
      }
    }
  }
  if (Test-Path $setup) {
    Log ("instalador: " + [math]::Round((Get-Item $setup).Length / 1MB) + " MB")
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
$s2 = Get-Item "C:\demo-stage2.bin" -ErrorAction SilentlyContinue
$r3 += " | stage2=" + $(if ($s2) { "$([math]::Round($s2.Length / 1KB)) KB" } else { "inexistente" })
$errS2 = (Get-Content "C:\dd\stage2.err" -ErrorAction SilentlyContinue | Select-Object -First 3) -join " / "
if ($errS2) { $r3 += " | err: " + $errS2 }
if ($r3.Length -gt 700) { $r3 = $r3.Substring(0, 700) }
Write-Host ("::error::ROTA1 fase2: " + $f2 + " /// ROTA2: " + $ddl + " /// ROTA3: " + $r3)
throw "nao consegui baixar a demo oficial"
