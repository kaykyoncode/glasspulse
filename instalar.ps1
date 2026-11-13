# Instala as dependências locais, gera o ícone e cria os atalhos do CorePulse.
# Uso (PowerShell):  .\instalar.ps1            -> instala e cria atalhos (inicialização + área de trabalho)
#                    .\instalar.ps1 -SemInicio  -> não liga a inicialização automática
#                    .\instalar.ps1 -PastaAtalhos "C:\caminho"  -> onde criar o atalho de abrir
param([switch]$SemInicio, [string]$PastaAtalhos = "")

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"

Write-Host "1/3  Dependências (PySide6 + psutil) em .libs ..."
& $python -m pip install --target (Join-Path $raiz ".libs") -r (Join-Path $raiz "requirements.txt") --no-warn-script-location --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "Não foi possível instalar as dependências do CorePulse." }
& $python (Join-Path $raiz "corepulse.pyw") --migrar-config
if ($LASTEXITCODE -ne 0) { throw "Não foi possível migrar as configurações do CorePulse." }

Write-Host "2/3  Ícone ..."
& $python (Join-Path $raiz "ferramentas\gerar_icone.py")

function Novo-Atalho($caminho) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($caminho)
    $s.TargetPath = $pythonw
    $s.Arguments = "`"$(Join-Path $raiz 'corepulse.pyw')`""
    $s.WorkingDirectory = $raiz
    $s.IconLocation = (Join-Path $raiz "assets\icone.ico")
    $s.Description = "CorePulse (widget de recursos)"
    $s.WindowStyle = 7
    $s.Save()
    # Só remove os atalhos anteriores depois que o novo estiver salvo.
    foreach ($nome in @("Monitor do PC.lnk", "GlassPulse.lnk")) {
        $antigo = Join-Path (Split-Path -Parent $caminho) $nome
        if (Test-Path -LiteralPath $antigo) {
            $anterior = (New-Object -ComObject WScript.Shell).CreateShortcut($antigo)
            if ($anterior.Arguments -match 'monitor_pc\.pyw|corepulse\.pyw') {
                Remove-Item -LiteralPath $antigo
            }
        }
    }
}

Write-Host "3/3  Atalhos ..."
$desktop = [Environment]::GetFolderPath("Desktop")
if ($PastaAtalhos -eq "") {
    # usa "Desktop\05 Atalhos" se existir; senão, a própria área de trabalho
    $PastaAtalhos = if (Test-Path (Join-Path $desktop "05 Atalhos")) { Join-Path $desktop "05 Atalhos" } else { $desktop }
}
Novo-Atalho (Join-Path $PastaAtalhos "CorePulse.lnk"); Write-Host "     $PastaAtalhos\CorePulse.lnk"
if (-not $SemInicio) {
    $inicio = [Environment]::GetFolderPath("Startup")
    Novo-Atalho (Join-Path $inicio "CorePulse.lnk"); Write-Host "     $inicio\CorePulse.lnk"
}
Write-Host "Pronto. Para abrir agora: Start-Process `"$pythonw`" '`"$raiz\corepulse.pyw`"'"
