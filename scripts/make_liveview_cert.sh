#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <pi-lan-ip>" >&2
  exit 2
fi

ip="$1"
out_dir="certs"
cert="$out_dir/liveview-$ip.crt"
key="$out_dir/liveview-$ip.key"

mkdir -p "$out_dir"
openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
  -keyout "$key" \
  -out "$cert" \
  -subj "/CN=$ip" \
  -addext "subjectAltName=IP:$ip"

echo "TLS certificate: $cert"
echo "TLS private key:  $key"
