#!/usr/bin/env python3
"""Create larger PARSEC simdev inputs for 1M trace collection.

The 100k pilot used tiny simdev inputs. For 1M drmemtrace collection, some
programs finish before enough memory references are observed. This script
creates deterministic larger local inputs inside the WSL PARSEC workspace.
"""

from pathlib import Path


def expand_blackscholes():
  source = Path("/root/qmap-work/parsec-inputs/blackscholes-simdev/in_16.txt")
  target = Path("/root/qmap-work/parsec-inputs/blackscholes-1m/in_262144.txt")
  target.parent.mkdir(parents=True, exist_ok=True)
  if target.exists():
    return

  lines = source.read_text(encoding="utf-8").splitlines()
  count = int(lines[0])
  body = lines[1:]
  if len(body) != count:
    raise RuntimeError(
        "Unexpected blackscholes input: header={}, rows={}".format(
            count, len(body)))

  target_count = 262144
  with target.open("w", encoding="utf-8") as output:
    output.write("{}\n".format(target_count))
    for index in range(target_count):
      output.write(body[index % len(body)] + "\n")


def expand_dedup():
  source = Path("/root/qmap-work/parsec-inputs/dedup-simdev/hamlet.dat")
  target = Path("/root/qmap-work/parsec-inputs/dedup-1m/hamlet_64x.dat")
  target.parent.mkdir(parents=True, exist_ok=True)
  if target.exists():
    return

  data = source.read_bytes()
  with target.open("wb") as output:
    for _ in range(64):
      output.write(data)


def main():
  expand_blackscholes()
  expand_dedup()
  print("Prepared PARSEC 1M input files.")


if __name__ == "__main__":
  main()
