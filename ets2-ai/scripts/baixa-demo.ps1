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
  if (Test-Path $setup) {
    Log "instalador CACHEADO (actions/cache) — pulando downloads"
  } elseif ($url2) {
    # 2) BAIXA o downloadnow direto em ARQUIVO — 3 motores:
    #    curl (com exit code logado) -> IWR (streaming p/ disco) -> BITS.
    #    Run 38183604100: curl -o criou 0 bytes sem erro visivel (-s
    #    engoliu); run 38181824100 PROVOU que a URL serve o instalador.
    New-Item -ItemType Directory -Force -Path "C:\dd" | Out-Null
    # v12: DOWNLOAD PARALELO POR RANGES — o CDN entrega ~2 MB/s por
    # conexao (runs 38385937916/38394298922 morreram no timeout); com 12
    # conexoes o ZIP de 5,97 GB cai de ~50 min para ~6 min.
    # v14: probe REAL de range — o header accept-ranges do HEAD some atras
    # de Cloudflare e o paralelo nunca ligava (runs v12/v13: curl simples
    # a ~1 MB/s). Um GET de 1 byte (r 0-0) responde 206 se ranges existem
    # e o content-range traz o tamanho TOTAL.
    $codeprobe = & curl.exe -s -D C:\dd\probe.h -o C:\dd\probe.bin -r 0-0 -w "%{http_code}" -A $ua -H "Referer: $ref" --max-time 40 $url2 2>$null
    $aceitaRange = ("$codeprobe" -eq "206")
    $tamRemoto = 0
    $ph = Get-Content C:\dd\probe.h -ErrorAction SilentlyContinue
    foreach ($ln in $ph) {
      if ("$ln" -match "(?i)^content-range:\s*bytes\s+0-0/(\d+)") { $tamRemoto = [int64]$Matches[1] }
    }
    Log ("probe: HTTP $codeprobe | total $tamRemoto bytes | ranges: $aceitaRange")
    $r3 = ""
    if ($aceitaRange -and $tamRemoto -gt 500MB) {
      $n = 12
      $parte = [math]::Floor($tamRemoto / $n)
      # v16: ORCAMENTO — para de lancar rodadas novas no minuto 200 para
      # o save do cache (upload de ~6 GB) + extracao + boot caberem no
      # timeout de 360. Partes baixadas ficam no cache (progresso salvo).
      $orcamento = (Get-Date).AddMinutes(200)
      # v15: ate 4 RODADAS — so refaz as partes que falharam/estolaram
      # (speed-limit aborta conexao lenta; parte boa fica no disco)
      for ($rodada = 1; $rodada -le 4; $rodada++) {
        if ((Get-Date) -gt $orcamento) { Log "orcamento de partes esgotado — progresso fica no cache"; break }
        $procs = @()
        $faltando = @()
        for ($k = 0; $k -lt $n; $k++) {
          $ini = $k * $parte
          $fim = $tamRemoto - 1
          if ($k -lt ($n - 1)) { $fim = $ini + $parte - 1 }
          $esperado = $fim - $ini + 1
          $f = Get-Item "C:\dd\part$k.bin" -ErrorAction SilentlyContinue
          if ($f -and $f.Length -eq $esperado) { continue }
          $faltando += $k
          if ($f) { Remove-Item $f.FullName -Force }
          $procs += Start-Process -FilePath "curl.exe" -ArgumentList @("-sL","-A",$ua,"-H","Referer: $ref","--max-time","2400","--speed-limit","524288","--speed-time","120","-r","$ini-$fim","-o","C:\dd\part$k.bin",$url2) -PassThru -WindowStyle Hidden
        }
        if (-not $faltando) { Log "todas as 12 partes completas (rodada $rodada)"; break }
        Log ("rodada $rodada baixando partes: " + ($faltando -join ","))
        $procs | Wait-Process -Timeout 2500 -ErrorAction SilentlyContinue
        $procs | Where-Object { -not $_.HasExited } | Stop-Process -Force -ErrorAction SilentlyContinue
      }
      $tamSoma = 0
      foreach ($k in 0..($n - 1)) {
        $f = Get-Item "C:\dd\part$k.bin" -ErrorAction SilentlyContinue
        if ($f) { $tamSoma += $f.Length }
      }
      Log ("soma das partes: $tamSoma de $tamRemoto")
      if ($tamSoma -eq $tamRemoto) {
        $lista = (0..($n - 1) | ForEach-Object { "C:\dd\part$_.bin" }) -join "+"
        cmd /c "copy /b $lista C:\demo-stage2.bin" *> $null
        $r3 = "paralelo OK"
      } else {
        Log "paralelo incompleto — remontando com o curl simples"
      }
    }
    if (-not (Test-Path $stage2) -or (Get-Item $stage2).Length -lt 1KB) {
      $w = & curl.exe -sSL --max-time 3000 --speed-limit 2097152 --speed-time 90 -A $ua -H "Referer: $ref" --retry 2 -w "%{http_code} %{size_download} %{url_effective}" -o $stage2 $url2 2> C:\dd\stage2.err
      Log ("curl simples exit: $LASTEXITCODE | $w")
      $r3 = "curl=$LASTEXITCODE $w"
    }
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
        # run 38262706763: o href e RELATIVO (/downloads/downloadnowfile/...)
        # com &amp; codificado — regex absoluta nao casava NADA
        $rx = "https?://[^" + '"' + "'" + "<>\s]*downloadnowfile[^" + '"' + "'" + "<>\s]*"
        $m = [regex]::Matches($txt, $rx) | ForEach-Object { $_.Value } | Select-Object -Unique
        if (-not $m) {
          $rxrel = "/downloads/downloadnowfile/5653/[^" + '"' + "'" + "<>\s]*"
          $m = [regex]::Matches($txt, $rxrel) | ForEach-Object { "https://www.techspot.com" + ($_.Value -replace "&amp;", "&") } | Select-Object -Unique
        }
        if (-not $m) {
          $rx2 = "https?://[^" + '"' + "'" + "<>\s]+\.exe"
          $m = [regex]::Matches($txt, $rx2) | ForEach-Object { $_.Value } | Select-Object -Unique
        }
        Log ("links no estagio 2: " + ($m -join " | "))
        if (-not $m) {
          # o CI recebe variante da pagina sem o link (run 38259230709):
          # tenta SEM --compressed e SEM Referer; e dumpa o head no log
          $h2 = & curl.exe -sL --max-time 90 -A $ua $url2 2>$null
          $t2 = $h2 -join " "
          Log ("variante sem compressed/referer: " + $t2.Length + " chars")
          $m = [regex]::Matches($t2, $rx) | ForEach-Object { $_.Value } | Select-Object -Unique
          if (-not $m) {
            $m = [regex]::Matches($t2, $rxrel) | ForEach-Object { "https://www.techspot.com" + ($_.Value -replace "&amp;", "&") } | Select-Object -Unique
          }
          if (-not $m) {
            $m = [regex]::Matches($t2, $rx2) | ForEach-Object { $_.Value } | Select-Object -Unique
          }
          Log ("links na variante: " + ($m -join " | "))
          if (-not $m) {
            Log ("HEAD estagio2: " + $txt.Substring(0, [math]::Min(500, $txt.Length)))
            $hrefs = [regex]::Matches($txt, "href=[^ >]{10,90}") | ForEach-Object { $_.Value } | Select-Object -Unique -First 10
            Log ("hrefs: " + ($hrefs -join " | "))
          }
        }
        if ($m -and -not (Test-Path $setup)) {
          $url3 = @($m)[0]
          Log ("URL do arquivo: " + $url3)
          $w3 = & curl.exe -sSL --compressed --max-time 1500 -A $ua -e $ref --retry 3 -w "%{http_code} %{size_download} %{content_type}" -o $setup $url3 2> C:\dd\setup.err
          Log ("setup curl exit: $LASTEXITCODE | $w3")
          $r3 += " | setup: $LASTEXITCODE $w3"
        }
      }
    }
  }
  if (Test-Path $setup) {
    $tamS = (Get-Item $setup).Length
    Log ("instalador: " + [math]::Round($tamS / 1MB) + " MB")
    # diagnostico do PE: machine type (run 38280133452: 5689 MB baixados
    # mas 'not a valid application for this OS platform')
    try {
      $fs = [System.IO.File]::OpenRead($setup)
      $hdr = New-Object byte[] 64
      $null = $fs.Read($hdr, 0, 64); $fs.Close()
      $hex = ($hdr[0..15] | ForEach-Object { $_.ToString("X2") }) -join " "
      $peOff = [BitConverter]::ToInt32($hdr, 0x3C)
      Log ("header: " + $hex + " | PE offset: " + $peOff)
      if ($peOff -gt 0 -and $peOff -lt 1000) {
        $fs = [System.IO.File]::OpenRead($setup)
        $pes = New-Object byte[] 6
        $fs.Position = $peOff; $null = $fs.Read($pes, 0, 6); $fs.Close()
        $mach = [BitConverter]::ToUInt16($pes, 4)
        $arq = @{ 0x8664 = "x64"; 0x14c = "x86"; 0xAA64 = "ARM64"; 0x1c0 = "ARM" }[[int]$mach]
        Log ("PE machine: 0x" + $mach.ToString("X4") + " (" + ($arq ?? "?") + ")")
        $r3 += " | PE=" + $mach.ToString("X4")
      }
    } catch { Log ("PE diag: " + $_.Exception.Message) }
    # HEAD: download veio completo?
    try {
      $cl = & curl.exe -sI -A $ua -e $ref $url3 2>$null | Select-String -Pattern "Content-Length:\s*(\d+)"
      if ($cl) {
        $esperado = [int64]$cl.Matches[0].Groups[1].Value
        if ($esperado -gt $tamS) {
          Log ("TRUNCADO: esperado $esperado, baixado $tamS — retomando")
          & curl.exe -sSL --compressed --max-time 1500 -A $ua -e $ref --retry 3 -C - -o $setup $url3
          Log ("resume exit: $LASTEXITCODE | agora: " + [math]::Round((Get-Item $setup).Length / 1MB) + " MB")
        } else {
          Log ("completo: Content-Length $esperado = baixado $tamS")
        }
      }
    } catch {}
    # fallback: extrair com 7-Zip (SFX/Inno — 7z abre a maioria)
    $sz7 = "C:\Program Files\7-Zip\7z.exe"
    if (Test-Path $sz7) {
      Log "tentando extrair com 7-Zip..."
      & $sz7 x -y -o"C:\demo-extract" $setup *> "C:\dd\7z.log"
      Log ("7z exit: $LASTEXITCODE")
      Get-Content "C:\dd\7z.log" -ErrorAction SilentlyContinue | Select-Object -Last 8 | ForEach-Object { Log ("7z: " + $_) }
      Log "arquivos extraidos:"
      Get-ChildItem "C:\demo-extract" -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { Log ("  " + $_.Name + " (" + [math]::Round($_.Length / 1MB) + " MB)") }
      # jogo direto no zip?
      $exe7 = Get-ChildItem "C:\demo-extract" -Recurse -Filter "eurotrucks2.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($exe7) {
        Log ("7z achou o JOGO: " + $exe7.FullName)
        New-Item -ItemType Directory -Force "C:\ets2demo\bin\win_x64" | Out-Null
        $raiz7 = Split-Path (Split-Path $exe7.FullName -Parent) -Parent
        Copy-Item (Join-Path $raiz7 "*") "C:\ets2demo\" -Recurse -Force -ErrorAction SilentlyContinue
        $r3 += " | 7z extraiu o JOGO"
      } else {
        # o zip traz o INSTALADOR — roda ele (run 38283415971: 4 arquivos,
        # nenhum era o jogo; provavelmente setup.exe + bins)
        $inst = Get-ChildItem "C:\demo-extract" -Recurse -Include *.exe -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match "euro|setup|install|ets2|demo" } | Select-Object -First 1
        if (-not $inst) {
          $inst = Get-ChildItem "C:\demo-extract" -Recurse -Include *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        $msi = Get-ChildItem "C:\demo-extract" -Recurse -Include *.msi -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($inst) {
          Log ("instalador extraido: " + $inst.FullName + " (" + [math]::Round($inst.Length / 1MB) + " MB)")
          foreach ($flag in @("/S", "/VERYSILENT", "/S /D=C:\ets2demo")) {
            try { $null = Start-Process -FilePath $inst.FullName -ArgumentList $flag -Wait -PassThru } catch { Log ("inst: " + $_.Exception.Message) }
            if (Test-Path $alvo) { break }
          }
          $r3 += " | rodou " + $inst.Name
        } elseif ($msi) {
          Log ("msi: " + $msi.FullName)
          $null = Start-Process msiexec -ArgumentList ("/i", "`"$($msi.FullName)`"", "/qn", "INSTALLDIR=C:\ets2demo") -Wait -PassThru
          $r3 += " | msiexec"
        }
      }
    }
    # instaladores SCS: /S (NSIS) ou /VERYSILENT (Inno); tenta ambos
    foreach ($flag in @("/S", "/VERYSILENT")) {
      try { $p = Start-Process -FilePath "C:\demo-setup.exe" -ArgumentList $flag -Wait -PassThru } catch { Log ("Start-Process: " + $_.Exception.Message); break }
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
