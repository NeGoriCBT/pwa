param(
    [string]$SourceDir = "PWA",
    [string]$BackupDir = "backups",
    [int]$MaxSlots = 15
)

$ErrorActionPreference = "Stop"

if ($MaxSlots -lt 1) {
    throw "MaxSlots must be >= 1"
}

$root = Get-Location
$sourcePath = Join-Path $root $SourceDir
$backupPath = Join-Path $root $BackupDir
$indexFile = Join-Path $backupPath "pwa-backup-index.json"

if (!(Test-Path $sourcePath)) {
    throw "Source directory not found: $sourcePath"
}

if (!(Test-Path $backupPath)) {
    New-Item -ItemType Directory -Path $backupPath | Out-Null
}

$slot = 1
if (Test-Path $indexFile) {
    try {
        $meta = Get-Content $indexFile -Raw | ConvertFrom-Json
        $current = [int]$meta.currentSlot
        if ($current -ge 1 -and $current -le $MaxSlots) {
            $slot = $current + 1
            if ($slot -gt $MaxSlots) { $slot = 1 }
        }
    } catch {
        $slot = 1
    }
}

$slotText = "{0:D2}" -f $slot
$archiveName = "PWA_backup_slot_${slotText}.zip"
$archivePath = Join-Path $backupPath $archiveName

if (Test-Path $archivePath) {
    Remove-Item $archivePath -Force
}

Compress-Archive -Path (Join-Path $sourcePath "*") -DestinationPath $archivePath -CompressionLevel Optimal

$metaOut = [ordered]@{
    currentSlot = $slot
    maxSlots = $MaxSlots
    updatedAt = (Get-Date).ToString("s")
    archive = $archiveName
}
$metaOut | ConvertTo-Json | Set-Content $indexFile -Encoding UTF8

Write-Output "Backup created: $archiveName (slot $slot/$MaxSlots)"
