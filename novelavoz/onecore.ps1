param([string]$InputFile, [switch]$List)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
$available = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($List) {
    $voices = @($available | ForEach-Object {
        @{id=$_.Id; name=$_.DisplayName; lang=$_.Language; engine='onecore'; installed=$true}
    })
    ConvertTo-Json -InputObject $voices -Compress
    exit
}
$request = Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
$speaker = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$stream = $null
$output = $null
try {
    $voice = $available | Where-Object {$_.Id -eq $request.voice} | Select-Object -First 1
    if ($null -eq $voice) { throw 'Windows no expone esta voz mediante OneCore.' }
    $speaker.Voice = $voice
    $speaker.Options.SpeakingRate = [double]$request.speed
    $speaker.Options.AudioVolume = [double]$request.volume
    $operation = $speaker.SynthesizeTextToStreamAsync([string]$request.text)
    $null = [Windows.Media.SpeechSynthesis.SpeechSynthesisStream, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($operation))
    $task.Wait()
    $speech = $task.Result
    $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($speech)
    $output = [System.IO.File]::Create($request.output)
    $stream.CopyTo($output)
} finally {
    if ($null -ne $output) { $output.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
    $speaker.Dispose()
}
