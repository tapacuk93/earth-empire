#!/bin/sh
# Generates the mock media the fixture points at (mock/media). Synthetic, so it is free to publish.
# Requires ffmpeg. Output is committed, so this only needs to run when the fixture changes.
set -e
cd "$(dirname "$0")/../mock"
rm -rf media && mkdir -p media
F="ffmpeg -hide_banner -loglevel error -y"

img() { # name w h c0 c1 type seed
  $F -f lavfi -i "gradients=s=$2x$3:c0=$4:c1=$5:type=$6:seed=$7:n=2" -frames:v 1 -q:v 5 "media/$1.jpg"
  $F -i "media/$1.jpg" -vf "scale=360:-2" -q:v 6 "media/$1.thumb.jpg"
}
frac() { # name w h start_scale
  $F -f lavfi -i "mandelbrot=s=$2x$3:start_scale=$4:outer=normalized_iteration_count" -frames:v 1 -q:v 5 "media/$1.jpg"
  $F -i "media/$1.jpg" -vf "scale=360:-2" -q:v 6 "media/$1.thumb.jpg"
}
vid() { # name w h seconds c0 c1 freq
  $F -f lavfi -i "gradients=s=$2x$3:c0=$5:c1=$6:type=radial:speed=0.04:duration=$4:rate=24" \
     -f lavfi -i "sine=frequency=$7:duration=$4" \
     -vf "format=yuv420p" -c:v libx264 -profile:v main -preset veryfast -crf 34 -c:a aac -b:a 32k \
     -movflags +faststart -shortest "media/$1.mp4"
  $F -ss 0.5 -i "media/$1.mp4" -frames:v 1 -vf "scale=360:-2" -q:v 6 "media/$1.thumb.jpg"
  # Stands in for the backend's AI-chosen best frame (media[].cover).
  $F -ss "$(echo "$4 * 0.6" | bc)" -i "media/$1.mp4" -frames:v 1 -vf "scale=540:-2" -q:v 5 "media/$1.cover.jpg"
}

vid reel-sunset 540 960 9 0xff7a18 0x3a1c71 440
img city-1 720 900 0x1e3c72 0x2a5298 linear 1
img city-2 720 900 0xee9ca7 0xffdde1 radial 2
img city-3 720 900 0x0f2027 0x2c5364 circular 3
img story-dune 720 1280 0xf7971e 0xffd200 linear 4
vid story-share 540 960 6 0x00b4db 0x0083b0 330
vid ocean-reel 540 960 8 0x1a2980 0x26d0ce 262
img food-bowl 720 720 0xf12711 0xf5af19 radial 5
vid story-market 540 960 6 0x56ab2f 0xa8e063 523
img mountain-post 720 900 0x134e5e 0x71b280 linear 6
frac mountain-orig-1 720 900 3
frac mountain-orig-2 720 900 1.5
vid reel-cooking 540 960 10 0xcb2d3e 0xef473a 294
img mix-1 720 900 0x654ea3 0xeaafc8 spiral 7
vid mix-2 544 680 5 0x355c7d 0xc06c84 349
img story-coffee 720 1280 0x3e5151 0xdecba4 radial 8
i=1
while [ $i -le 18 ]; do
  img "filler-$i" 720 720 "0x$(printf '%02x' $((i*13%256)))5a8c" "0xe0$(printf '%02x' $((i*29%256)))70" circular $((i+20))
  i=$((i+1))
done
img hl-travel 300 300 0xf7971e 0xffd200 radial 31
img hl-food 300 300 0xf12711 0xf5af19 radial 32
img hl-ocean 300 300 0x1a2980 0x26d0ce radial 33
img avatar 320 320 0x0f9b0f 0x000000 radial 34
du -sh media
