# PROVA DE TRABALHO (v0.4.23) — ciclo completo no CI.
# O jogo-substituto roda com --trabalho (reboque a acoplar, rota com
# BALSA, doca no final) e o MESMO exe da release tem que fazer tudo:
# chegar no reboque, ACOPAR (T), seguir o GPS ate o porto, EMBARCAR na
# balsa (Enter), cruzar e ENTREGAR na doca.
# Roda no job prova-de-direcao (Windows) com cwd = raiz do repo.
$ErrorActionPreference = "Stop"
$g = "C:\Juegos\Euro Truck Simulator 2 Opti\gamedata"
$exe = (Resolve-Path "dist\ETS2-AI-bridge.exe").Path
$env:PYTHONUNBUFFERED = "1"

# 1) o JOGO com o CICLO DE TRABALHO (mesmo padrao da prova de direcao)
$game = Start-Process -FilePath "$g\bin\win_x64\eurotrucks2.exe" -ArgumentList "--segundos","560","--trabalho","--saida","C:\Juegos\trabalho.json" -WorkingDirectory $g -RedirectStandardError "C:\Juegos\trabalho.err" -PassThru
Start-Sleep -Seconds 8

# 2) o BRIDGE (exe da release) em drive com injecao
$p = Start-Process -FilePath $exe -ArgumentList "--ets2","drive","--inject" -WorkingDirectory "C:\Juegos" -RedirectStandardOutput "C:\Juegos\bridge2.log" -RedirectStandardError "C:\Juegos\bridge2.err" -PassThru

# 3) a janela do JOGO em 1o plano (gate do injetor)
$wsh = New-Object -ComObject WScript.Shell
1..8 | ForEach-Object { Start-Sleep -Seconds 2; $null = $wsh.AppActivate("Euro Truck Simulator 2 Opti") }

# 4) espera o jogo terminar (560 s de simulacao + margem)
if (-not $game.WaitForExit(720000)) { Stop-Process -Id $game.Id -Force }
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue

# 5) le o resultado e EXIGE o ciclo completo
if (-not (Test-Path "C:\Juegos\trabalho.json")) {
  Write-Host "=== trabalho.err ==="
  Get-Content "C:\Juegos\trabalho.err" -ErrorAction SilentlyContinue
  Write-Host "::error::TRABALHO: o jogo-substituto nao terminou (sem trabalho.json)"
  exit 1
}
$t = Get-Content "C:\Juegos\trabalho.json" -Raw | ConvertFrom-Json
Write-Host "=== resultado do trabalho ==="
$t | ConvertTo-Json -Depth 4 | Write-Host
$t.log | Select-Object -Last 12 | ForEach-Object { Write-Host "  $_" }
$diag = "fase=$($t.fase) acoplou=$($t.acoplou) balsa=$($t.pegou_balsa) entregou=$($t.entregou) T=$($t.teclas_T) Enter=$($t.teclas_enter) dist=$($t.dist_m)"
if (-not $t.acoplou) { Write-Host "::error::TRABALHO: nao acoplou o reboque | $diag"; exit 1 }
if (-not $t.pegou_balsa) { Write-Host "::error::TRABALHO: nao pegou a balsa | $diag"; exit 1 }
if (-not $t.entregou) { Write-Host "::error::TRABALHO: nao entregou | $diag"; exit 1 }
if ([int]$t.teclas_T -lt 1 -or [int]$t.teclas_enter -lt 1) { Write-Host "::error::TRABALHO: faltaram as teclas de interacao | $diag"; exit 1 }
if ([double]$t.dist_m -lt 100) { Write-Host "::error::TRABALHO: andou pouco | $diag"; exit 1 }
if (-not $t.mmf_magic_ok -or -not $t.mmf_valores_ok) { Write-Host "::error::TRABALHO: MMF invalida | $diag"; exit 1 }
if ([int]$t.canais_dll -lt 8) { Write-Host "::error::TRABALHO: poucos canais | $diag"; exit 1 }
Write-Host ("PROVA DE TRABALHO: ciclo COMPLETO — acoplou o reboque (T), EMBARCOU na balsa (Enter), cruzou e ENTREGOU na doca — {0} m pela IA, GPS seguido, teclas reais" -f $t.dist_m)
