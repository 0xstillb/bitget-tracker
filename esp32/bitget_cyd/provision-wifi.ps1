[CmdletBinding()]
param(
    [string]$Port
)

$ErrorActionPreference = "Stop"
$defaultViewerUrl = "http://192.168.1.121:8080"

function Select-SerialPort {
    param([string]$RequestedPort)

    $ports = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
    if ($RequestedPort) {
        if ($ports -notcontains $RequestedPort.ToUpperInvariant()) {
            Write-Warning "Port $RequestedPort was not detected; attempting it anyway."
        }
        return $RequestedPort.ToUpperInvariant()
    }
    if ($ports.Count -eq 0) {
        throw "No COM port detected. Connect the ESP32 and try again."
    }
    Write-Host "Detected serial ports:" -ForegroundColor Cyan
    for ($index = 0; $index -lt $ports.Count; $index++) {
        Write-Host "  [$($index + 1)] $($ports[$index])"
    }
    $selection = Read-Host "Select a port number or type a port name"
    if ($selection -match '^[0-9]+$') {
        $selectedIndex = [int]$selection - 1
        if ($selectedIndex -lt 0 -or $selectedIndex -ge $ports.Count) {
            throw "Invalid port selection."
        }
        return $ports[$selectedIndex]
    }
    if ([string]::IsNullOrWhiteSpace($selection)) {
        throw "A COM port is required."
    }
    return $selection.Trim().ToUpperInvariant()
}

function Read-PlainPassword {
    $securePassword = Read-Host "Wi-Fi password (hidden)" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        $securePassword.Dispose()
    }
}

try {
    $selectedPort = Select-SerialPort -RequestedPort $Port
    Write-Host "Using $selectedPort" -ForegroundColor Green

    $ssid = Read-Host "Wi-Fi SSID"
    if ([string]::IsNullOrWhiteSpace($ssid)) {
        throw "Wi-Fi SSID is required."
    }
    $password = Read-PlainPassword
    $viewerUrl = Read-Host "Pi Viewer URL [$defaultViewerUrl]"
    if ([string]::IsNullOrWhiteSpace($viewerUrl)) {
        $viewerUrl = $defaultViewerUrl
    }
    $viewerUrl = $viewerUrl.Trim().TrimEnd('/')
    if ($viewerUrl -notmatch '^https?://') {
        throw "Pi Viewer URL must start with http:// or https://."
    }

    $payload = [ordered]@{
        cmd = "set_wifi"
        ssid = $ssid
        password = $password
        viewer_url = $viewerUrl
    } | ConvertTo-Json -Compress

    $serial = New-Object System.IO.Ports.SerialPort($selectedPort, 115200, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One))
    $serial.Handshake = [System.IO.Ports.Handshake]::None
    $serial.ReadTimeout = 500
    $serial.WriteTimeout = 2000
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    try {
        $serial.Open()
        Start-Sleep -Seconds 2
        $serial.DiscardInBuffer()
        $serial.WriteLine($payload)
        Write-Host "Configuration sent. Waiting for ESP32 response..." -ForegroundColor Yellow

        $deadline = (Get-Date).AddSeconds(8)
        $response = $null
        while ((Get-Date) -lt $deadline) {
            try {
                $line = $serial.ReadLine()
                if ($line -match '"ok"\s*:\s*(true|false)') {
                    $response = $line.Trim()
                    break
                }
            }
            catch [TimeoutException] {
                continue
            }
        }
        if (-not $response) {
            throw "No JSON response. Check that Task 24 firmware is flashed and the selected port is correct."
        }
        Write-Host "ESP32 response: $response"
        if ($response -notmatch '"ok"\s*:\s*true') {
            throw "ESP32 rejected the configuration."
        }
        Write-Host "Success. The ESP32 is restarting; wait for LIVE on the screen." -ForegroundColor Green
    }
    finally {
        if ($serial.IsOpen) {
            $serial.Close()
        }
        $serial.Dispose()
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
finally {
    $password = $null
    $payload = $null
}
