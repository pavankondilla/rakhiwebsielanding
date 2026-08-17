<#
.SYNOPSIS
    Rebuild the logo assets and sync the company name across the whole site.

.DESCRIPTION
    A thin, careful wrapper around tools\rebrand.py. It finds a usable Python,
    installs Pillow and numpy the first time if they are missing, runs the
    rebrand, and can open the generated preview images for you.

    Everything it does is driven by tools\brand.json. Edit that file to make a
    change permanent; use the switches below to try one out first.

.PARAMETER Name
    Company name, e.g. "AiRakhi". The wordmark is split at the last
    lowercase-to-uppercase seam and the second half is drawn in the rose accent.

.PARAMETER Logo
    Master logo file, relative to the repo root. Any size from 512x512 up;
    PNG with or without transparency.

.PARAMETER Crop
    Which part of the master file is the emblem:
      none            the whole artwork  (right for a plain mark)
      auto            keep existing transparency, else split at a clear band
      top:606         everything above y=606
      box:x,y,w,h     an exact rectangle
    Run with -Map first if you are not sure -- it writes a ruled copy of the
    logo so you can read the y value straight off the image.

.PARAMETER BaseUrl
    The URL the site is really served from, trailing slash included. Drives
    canonical, og:url, og:image, twitter:image, sitemap.xml, robots.txt and the
    404 link. Point it at a domain that is parked or not yet wired to Pages and
    those tags fail silently -- the page looks fine while search engines and
    share previews follow them somewhere else.

.PARAMETER Open
    Open the generated preview images when the run finishes.

.EXAMPLE
    .\rebrand.ps1
    Rebuild everything from tools\brand.json.

.EXAMPLE
    .\rebrand.ps1 -Map -Open
    Write a ruled copy of the logo and open it, to choose a -Crop value.

.EXAMPLE
    .\rebrand.ps1 -Logo new-logo.png -Crop none -Preview -Open
    Swap in a new logo, render the assets, and look at them.

.EXAMPLE
    .\rebrand.ps1 -Name "AiRakhi" -Domain airakhi.online -WebHost www.airakhi.online -Save
    Rename the company everywhere and remember it in brand.json.
#>
[CmdletBinding()]
param(
    [string]$Name,
    [string]$Logo,
    [string]$Crop,
    [string]$Tagline,
    [string]$Domain,
    [Alias('Host')][string]$WebHost,   # $Host is reserved in PowerShell, hence WebHost
    [string]$BaseUrl,
    [ValidateSet('assets', 'text')][string]$Only,
    [switch]$Map,
    [switch]$Preview,
    [switch]$Check,
    [switch]$DryRun,
    [switch]$Save,
    [switch]$Open,
    [switch]$Install,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra
)

# Deliberately not 'Stop': python and pip write progress and errors to stderr,
# and under 'Stop' Windows PowerShell turns that into a terminating
# NativeCommandError even on a successful run. Exit codes are checked by hand.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script = Join-Path $root 'tools\rebrand.py'

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "!!  $text" -ForegroundColor Yellow }
function Write-Bad ($text) { Write-Host "x   $text" -ForegroundColor Red }

if (-not (Test-Path -LiteralPath $script)) {
    Write-Bad "tools\rebrand.py is missing next to this script ($root)."
    exit 1
}

# --- 1. Find a Python that actually runs -------------------------------------
#
# On Windows "python" is often the Microsoft Store stub: it exists, resolves,
# and does nothing but open the Store. So every candidate is proved by running
# it, never by Get-Command alone.

$python = $null
$candidates = @(
    @{ Exe = 'py';      Args = @('-3') },
    @{ Exe = 'python';  Args = @() },
    @{ Exe = 'python3'; Args = @() }
)
foreach ($c in $candidates) {
    if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
    # No quotes anywhere in the probe: PowerShell strips them on the way to a
    # native exe, so the version is reported as one bare integer (3.14 -> 314).
    $probeArgs = $c.Args + @('-c', 'import sys;print(sys.version_info[0]*100+sys.version_info[1])')
    try {
        $probe = & $c.Exe $probeArgs
    } catch { continue }
    if ($LASTEXITCODE -ne 0 -or -not $probe) { continue }
    $n = 0
    if (-not [int]::TryParse("$probe".Trim(), [ref]$n)) { continue }
    $ver = "{0}.{1}" -f [math]::Floor($n / 100), ($n % 100)
    if ($n -lt 309) {
        Write-Warn "$($c.Exe) is Python $ver; 3.9 or newer is needed. Trying the next one."
        continue
    }
    $python = $c
    Write-Step "Python $ver via '$($c.Exe) $($c.Args -join ' ')'"
    break
}
if (-not $python) {
    Write-Bad 'No usable Python found.'
    Write-Host '    Install it from https://www.python.org/downloads/ and tick'
    Write-Host '    "Add python.exe to PATH", then run this script again.'
    exit 1
}

function Invoke-Python { param([string[]]$PyArgs) & $python.Exe @($python.Args + $PyArgs) }

# --- 2. Make sure Pillow and numpy are there ---------------------------------

Invoke-Python @('-c', 'import numpy, PIL') | Out-Null
if ($LASTEXITCODE -ne 0 -or $Install) {
    Write-Step 'Installing Pillow and numpy (one time)'
    Invoke-Python @('-m', 'pip', 'install', '--upgrade', '--quiet', 'pillow', 'numpy')
    if ($LASTEXITCODE -ne 0) {
        Write-Bad 'pip could not install Pillow and numpy.'
        Write-Host '    Try it by hand:  python -m pip install --user --upgrade pillow numpy'
        exit 1
    }
    Invoke-Python @('-c', 'import numpy, PIL') | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Bad 'Pillow and numpy still will not import after installing.'
        exit 1
    }
}

# --- 3. Run the rebrand ------------------------------------------------------

$argv = @($script)
if ($Name)    { $argv += @('--name',    $Name) }
if ($Logo)    { $argv += @('--logo',    $Logo) }
if ($Crop)    { $argv += @('--crop',    $Crop) }
if ($Tagline) { $argv += @('--tagline', $Tagline) }
if ($Domain)  { $argv += @('--domain',  $Domain) }
if ($WebHost) { $argv += @('--host',    $WebHost) }
if ($BaseUrl) { $argv += @('--base-url', $BaseUrl) }
if ($Only)    { $argv += @('--only',    $Only) }
if ($Map)     { $argv += '--map' }
if ($Preview) { $argv += '--preview' }
if ($Check)   { $argv += '--check' }
if ($DryRun)  { $argv += '--dry-run' }
if ($Save)    { $argv += '--save' }
if ($Extra)   { $argv += $Extra }

Write-Step 'Rebranding'
Push-Location $root
try { Invoke-Python $argv } finally { Pop-Location }
$code = $LASTEXITCODE

# --- 4. Show the result ------------------------------------------------------

if ($code -eq 0) {
    Write-Host ''
    Write-Step 'Done.'
    if (-not $Check -and -not $DryRun -and -not $Map) {
        Write-Host '    Look it over, then publish:'
        Write-Host '      git add -A; git commit -m "Rebrand"; git push' -ForegroundColor DarkGray
    }
} elseif ($code -eq 2) {
    Write-Warn 'The run finished but verification found problems -- see above.'
} else {
    Write-Bad "rebrand.py exited with code $code."
}

if ($Open) {
    # Invoke-Item, not the call operator. `& 'logo.png'` asks PowerShell to
    # *execute* the file; in PowerShell 7 that fails outright ("not a valid
    # application for this OS platform"). Invoke-Item opens it in whatever app
    # the file type is associated with, which is what you actually want.
    $shown = @()
    foreach ($rel in @('tools\preview\crop-map.png', 'tools\preview\assets.png',
                       'assets\og-cover.jpg', 'assets\logo-mark.png')) {
        $path = Join-Path $root $rel
        if (Test-Path -LiteralPath $path) { $shown += $path }
    }
    if ($Map)     { $shown = $shown | Where-Object { $_ -like '*crop-map.png' } }
    elseif (-not $Preview) { $shown = $shown | Where-Object { $_ -notlike '*preview*' } }
    foreach ($path in $shown) {
        Write-Host "    opening $path" -ForegroundColor DarkGray
        Invoke-Item -LiteralPath $path
    }
    if (-not $shown) { Write-Warn 'Nothing to open -- add -Preview or -Map.' }
}

exit $code
