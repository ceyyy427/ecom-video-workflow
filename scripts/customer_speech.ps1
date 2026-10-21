param([Parameter(Mandatory=$true)][string]$TextPath, [Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $speaker.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
    if (-not $voice) { throw 'Install a classic zh-CN Windows speech voice, or use --voice-file with the matching script. No cloud fallback.' }
    $speaker.SelectVoice($voice.VoiceInfo.Name)
    $speaker.Rate = 2
    $speaker.SetOutputToWaveFile($OutputPath)
    $speaker.Speak([System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8))
} finally { $speaker.Dispose() }
