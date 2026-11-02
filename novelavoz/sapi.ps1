param([string]$InputFile, [switch]$List)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($List) {
        $voices = @($speaker.GetInstalledVoices() | Where-Object {$_.Enabled} | ForEach-Object {
            @{id=$_.VoiceInfo.Name; name=$_.VoiceInfo.Name; lang=$_.VoiceInfo.Culture.Name; engine='sapi'; installed=$true}
        })
        ConvertTo-Json -InputObject $voices -Compress
    } else {
        $request = Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $speaker.SelectVoice($request.voice)
        $speaker.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$request.rate))
        $speaker.Volume = [Math]::Max(0, [Math]::Min(100, [int]$request.volume))
        $speaker.SetOutputToWaveFile($request.output)
        $speaker.Speak($request.text)
    }
} finally { $speaker.Dispose() }
