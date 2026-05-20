param(
  [string]$Distro = "QMAP-Ubuntu-22.04",
  [string]$WslProject = "/root/qmap-work/cache_replacement",
  [string]$DynamoRIO = "/root/qmap-work/tools/extern/DynamoRIO-Linux-11.91.20581/bin64/drrun",
  [int]$MaxRecords = 1000000,
  [int]$SkipRecords = 100000,
  [int]$TraceRefMultiplier = 100
)

$ErrorActionPreference = "Stop"

$workloads = @(
  @{
    Name = "parsec_blackscholes"
    Binary = "/root/qmap-work/parsec-3.0/pkgs/apps/blackscholes/inst/amd64-linux.gcc-pthreads/bin/blackscholes"
    Args = "1 /root/qmap-work/parsec-inputs/blackscholes-1m/in_262144.txt /root/qmap-work/parsec-runs/blackscholes/prices_trace_1m.txt"
  },
  @{
    Name = "parsec_canneal"
    Binary = "/root/qmap-work/parsec-3.0/pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"
    Args = "1 1000 300 /root/qmap-work/parsec-inputs/canneal-simdev/100.nets 50"
  },
  @{
    Name = "parsec_streamcluster"
    Binary = "/root/qmap-work/parsec-3.0/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"
    Args = "3 10 16 65536 65536 1000 none /root/qmap-work/parsec-runs/streamcluster/output_trace_1m.txt 1"
  },
  @{
    Name = "parsec_dedup"
    Binary = "/root/qmap-work/parsec-3.0/pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"
    Args = "-c -p -v -t 1 -i /root/qmap-work/parsec-inputs/dedup-1m/hamlet_64x.dat -o /root/qmap-work/parsec-runs/dedup/output_trace_1m.dat.ddp"
  }
)

function Invoke-WslCommand {
  param([string]$Command)
  & wsl.exe -d $Distro -u root -- bash -lc $Command
  if ($LASTEXITCODE -ne 0) {
    throw "WSL command failed with exit code $LASTEXITCODE"
  }
}

function Get-WslPath {
  param([string]$WindowsPath)

  $resolved = (Resolve-Path -LiteralPath $WindowsPath).Path
  if ($resolved -match "^([A-Za-z]):\\(.*)$") {
    $drive = $Matches[1].ToLowerInvariant()
    $rest = $Matches[2] -replace "\\", "/"
    return "/mnt/$drive/$rest"
  }

  $escaped = $resolved -replace "\\", "\\"
  $path = (& wsl.exe -d $Distro -u root -- wslpath -a -- "$escaped" | Select-Object -Last 1)
  if ($LASTEXITCODE -ne 0 -or -not $path) {
    throw "Failed to convert Windows path to WSL path: $resolved"
  }
  return $path.Trim()
}

$repoWindows = (Get-Location).Path
$repoWsl = Get-WslPath $repoWindows
$tag = if (($MaxRecords % 1000000) -eq 0) { "$([int]($MaxRecords / 1000000))m" } else { "$MaxRecords" }
$runStamp = Get-Date -Format "yyyyMMddHHmmss"

Invoke-WslCommand "test -x '$DynamoRIO'"
Invoke-WslCommand "test -d '$WslProject/scripts'"
Invoke-WslCommand "mkdir -p '$WslProject/dataset/raw_traces' '$WslProject/outputs/results/real_trace_stats' '$repoWsl/dataset/raw_traces'"
Invoke-WslCommand "python3 '$repoWsl/scripts/prepare_parsec_1m_inputs.py'"

foreach ($workload in $workloads) {
  $name = $workload.Name
  $binary = $workload.Binary
  $args = $workload.Args
  $output = "$WslProject/dataset/raw_traces/${name}_${tag}.csv"
  $workDir = "/root/qmap-work/drmemtrace/${name}_${tag}_${runStamp}"
  $viewLog = "$WslProject/outputs/results/real_trace_stats/${name}_${tag}.view.log"

  Invoke-WslCommand "test -x '$binary'"
  $collect = @"
cd '$WslProject'
python3 scripts/collect_trace_drmemtrace.py \
  --drrun '$DynamoRIO' \
  --output '$output' \
  --work-dir '$workDir' \
  --max-records $MaxRecords \
  --skip-records $SkipRecords \
  --trace-ref-multiplier $TraceRefMultiplier \
  --view-log '$viewLog' \
  -- \
  '$binary' $args
"@
  Write-Host "[collect] $name -> ${name}_${tag}.csv"
  Invoke-WslCommand $collect
  Invoke-WslCommand "cp '$output' '$repoWsl/dataset/raw_traces/${name}_${tag}.csv'"
}

foreach ($workload in $workloads) {
  $name = $workload.Name
  $input = "dataset/raw_traces/${name}_${tag}.csv"
  $rawOutput = "dataset/raw_traces/${name}_${tag}_normalized.csv"
  $workloadName = "${name}_${tag}"
  Write-Host "[prepare] $workloadName"
  & python scripts/prepare_real_trace.py `
    --input $input `
    --workload $workloadName `
    --raw-output $rawOutput `
    --processed-dir dataset/processed `
    --manifest "dataset/metadata/real_workload_manifest_${tag}.json" `
    --stats-dir "outputs/results/real_trace_stats_${tag}" `
    --limit $MaxRecords
  if ($LASTEXITCODE -ne 0) {
    throw "prepare_real_trace.py failed for $workloadName"
  }
}

Write-Host "[done] Collected and prepared PARSEC $tag traces."
